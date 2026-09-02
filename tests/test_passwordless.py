"""Тесты схемы «без паролей в программе» (v1.4.0 → v1.5.0).

Пароль облачного аккаунта не зашит в код: его вводит сотрудник на
единственном экране входа, хранит Windows Credential Manager. Здесь
проверяются чистые функции core, обслуживающие эту схему:
распознавание ошибок авторизации и валидация адресов.
"""
import pathlib
import smtplib

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


# --- потрошенный mailto-флоу удалён ------------------------------------------


def test_password_request_helpers_removed():
    """Запрос пароля по почте (mailto/буфер обмена) удалён в v1.5.0:
    на машинах без почтовой программы он не работал и плодил окна.
    Пароль сотрудник запрашивает у администратора напрямую."""
    assert not hasattr(core, "build_password_request_mailto")
    assert not hasattr(core, "password_request_letter")


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
