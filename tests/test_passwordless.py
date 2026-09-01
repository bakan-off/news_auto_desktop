"""Тесты схемы «без паролей в программе» (v1.4.0).

Пароль облачного аккаунта больше не зашит в код: его вводит сотрудник
на экране настройки подключения, хранит Windows Credential Manager.
Здесь проверяются чистые функции core, обслуживающие эту схему:
распознавание ошибок авторизации и письмо-запрос пароля.
"""
import pathlib
import smtplib
from urllib.parse import parse_qs, unquote, urlparse

import core

# --- is_auth_error ----------------------------------------------------------


def test_auth_error_smtp_authentication():
    """Отказ SMTP-логина — это ошибка авторизации."""
    exc = smtplib.SMTPAuthenticationError(535, b"5.7.8 Error: authentication failed")
    assert core.is_auth_error(exc) is True


def test_auth_error_webdav_401():
    """WebDAV-клиент поднимает ResponseError с кодом 401 в тексте."""
    assert core.is_auth_error(Exception("ResponseError('401 Unauthorized')")) is True


def test_auth_error_auth_word():
    assert core.is_auth_error(Exception("SMTP AUTH extension not supported")) is True


def test_auth_error_login_password_text():
    assert core.is_auth_error(Exception("Incorrect Login/Password")) is True


def test_not_auth_error_network():
    """Сетевые/прочие сбои авторизацией не считаются: повтор имеет смысл."""
    assert core.is_auth_error(OSError("timed out")) is False


def test_not_auth_error_not_found():
    assert core.is_auth_error(Exception("Remote path not found")) is False


def test_not_auth_error_unrelated_words():
    # «exceeded» содержит… ничего общего с auth/401/login: ложных
    # срабатываний на случайных словах быть не должно
    assert core.is_auth_error(Exception("Maximum number of files exceeded")) is False


# --- письмо-запрос пароля ---------------------------------------------------


def test_mailto_recipient_and_params():
    """mailto адресован администратору и содержит тему с телом письма."""
    url = core.build_password_request_mailto("admin@lib.ru", "ivanov@lib.ru")
    parsed = urlparse(url)
    assert parsed.scheme == "mailto"
    assert parsed.path == "admin@lib.ru"
    qs = parse_qs(parsed.query)
    assert "КМЦБС" in unquote(qs["subject"][0])
    assert "пароль" in unquote(qs["body"][0])


def test_mailto_contains_sender_email():
    """В теле письма указана рабочая почта сотрудника — администратору
    понятно, кому передать пароль лично."""
    url = core.build_password_request_mailto("admin@lib.ru", "ivanov@lib.ru")
    assert "ivanov@lib.ru" in unquote(url)


def test_mailto_specials_are_quoted():
    """Кириллица и перевод строки кодируются — почтовая программа
    откроет ссылку без потерь."""
    url = core.build_password_request_mailto("a@b.ru", "c@d.ru")
    assert "%0A" in url or "%0a" in url  # перевод строки закодирован
    assert " " not in url


def test_request_letter_text():
    """Текст для буфера обмена содержит тему и те же ключевые фразы."""
    letter = core.password_request_letter("ivanov@lib.ru")
    assert letter.startswith("Тема:")
    assert "КМЦБС" in letter
    assert "пароль" in letter
    assert "ivanov@lib.ru" in letter


def test_mailto_and_letter_consistent():
    """Оба варианта письма говорят об одном и том же."""
    url = core.build_password_request_mailto("a@b.ru", "c@d.ru")
    letter = core.password_request_letter("c@d.ru")
    assert "КМЦБС Новости" in unquote(url)
    assert "КМЦБС Новости" in letter


# --- DEFAULTS без паролей ----------------------------------------------------


def test_defaults_contain_no_passwords():
    """Схема BYO-пароля: в main.DEFAULTS секретов быть не должно.

    main импортирует tkinter и в тестах недоступен как модуль GUI,
    поэтому проверяем исходник статически — защита от случайного
    возврата пароля в код.
    """
    source = pathlib.Path(__file__).resolve().parent.parent / "main.py"
    text = source.read_text(encoding="utf-8")
    # значения по умолчанию — пустые строки, не секреты
    assert '"webdav_password": ""' in text
    assert '"smtp_password": ""' in text
