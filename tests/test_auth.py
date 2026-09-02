"""Тесты входа v1.5.0: один экран, почта + общий пароль.

Кодов подтверждения больше нет: пароль — единственный барьер
(секретов в программе нет, пароль выдаёт владелец лично).
"""

import core

# --- размеры и политика ------------------------------------------------------


def test_login_policy_constants_sane():
    """Пауза после серии неудач защищает общий аккаунт от блокировки
    на стороне почтового сервера (mail.ru агрессивен к перебору)."""
    assert 3 <= core.LOGIN_MAX_ATTEMPTS <= 10
    assert core.LOGIN_LOCKOUT_SEC >= 30
    assert core.SMTP_TIMEOUT_SEC >= 5


def test_verification_code_removed():
    """Код подтверждения e-mail удалён в v1.5.0: без секретов в exe
    он дублировал сам пароль, добавляя лишний шаг «загляните в почту»."""
    assert not hasattr(core, "generate_verification_code")
    assert not hasattr(core, "VERIFICATION_CODE_TTL_SEC")
    assert not hasattr(core, "VERIFICATION_CODE_MAX_ATTEMPTS")


def test_pin_code_removed():
    # общий PIN-код входа удалён (v1.3): он зашивался в exe и не
    # останавливал постороннего
    assert not hasattr(core, "PIN_MAX_ATTEMPTS")
    assert not hasattr(core, "PIN_LOCKOUT_SEC")


# --- валидация адресов -------------------------------------------------------


def test_valid_email_accepted():
    assert core.is_valid_email("ivanov@library.ru") is True


def test_valid_email_strips_spaces():
    assert core.is_valid_email("  ivanov@library.ru ") is True


def test_invalid_email_rejected():
    for bad in ("", "ivanov", "ivanov@", "@library.ru", "a b@library.ru",
                "ivanov@library", "иванов@библиотека.рф x"):
        assert core.is_valid_email(bad) is False, bad


def test_validate_submission_requires_author_email():
    """Пустая или кривая почта автора — ошибка ещё до отправки."""
    err = core.validate_submission("", "Заголовок", "Описание", "плейсхолдер")
    assert err is not None and "Email" in err
    err = core.validate_submission("не-почта", "Заголовок", "Описание", "плейсхолдер")
    assert err is not None and "Email" in err


def test_validate_submission_accepts_valid_email():
    assert core.validate_submission("iv@lib.ru", "Заголовок", "Описание", "плейсхолдер") is None


# --- регрессия: строка подсказки в экране входа -------------------------------


def test_login_screen_mentions_admin_contact():
    """Экран входа говорит, куда обратиться за паролем (строкой, не
    кнопкой-мейлто). Проверяем статически: GUI в тестах не поднимаем."""
    source = __import__("pathlib").Path(__file__).resolve().parent.parent / "main.py"
    text = source.read_text(encoding="utf-8")
    assert "Не знаете пароль?" in text
    assert "mailto" not in text
    assert "Скопировать текст" not in text
