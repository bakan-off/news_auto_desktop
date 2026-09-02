"""Тесты входа (v1.5.0) и подтверждения почты автора (v1.6.0).

Вход: один экран — почта получателя + общий пароль, без кодов.
Почта АВТОРА подтверждается отдельно — кодом на указанную почту,
прямо в форме отправки, один раз до смены почты: администратор
отвечает на настоящий адрес.
"""
import pathlib
import re

import core

SOURCE = pathlib.Path(__file__).resolve().parent.parent / "main.py"
MAIN_TEXT = SOURCE.read_text(encoding="utf-8")


# --- размеры и политика ------------------------------------------------------


def test_login_policy_constants_sane():
    """Пауза после серии неудач защищает общий аккаунт от блокировки
    на стороне почтового сервера (mail.ru агрессивен к перебору)."""
    assert 3 <= core.LOGIN_MAX_ATTEMPTS <= 10
    assert core.LOGIN_LOCKOUT_SEC >= 30
    assert core.SMTP_TIMEOUT_SEC >= 5


def test_pin_code_removed():
    # общий PIN-код входа удалён (v1.3): он зашивался в exe и не
    # останавливал постороннего
    assert not hasattr(core, "PIN_MAX_ATTEMPTS")
    assert not hasattr(core, "PIN_LOCKOUT_SEC")


# --- код подтверждения почты ---------------------------------------------------


def test_verification_code_format():
    code = core.generate_verification_code()
    assert isinstance(code, str)
    assert re.fullmatch(r"\d{6}", code)


def test_verification_code_varies():
    # фиксированный seed (как у random) дал бы одинаковые коды
    codes = {core.generate_verification_code() for _ in range(50)}
    assert len(codes) > 1


def test_verification_policy_constants_sane():
    assert core.VERIFICATION_CODE_TTL_SEC >= 60
    assert core.VERIFICATION_CODE_MAX_ATTEMPTS >= 1
    assert core.VERIFICATION_CODE_RESEND_SEC >= 30


def test_verification_letter_contains_code():
    html = core.build_verification_email_html("123456")
    assert "123456" in html
    assert "КМЦБС" in html


def test_verification_letter_mentions_ttl():
    html = core.build_verification_email_html("123456")
    assert f"{core.VERIFICATION_CODE_TTL_SEC // 60} минут" in html


def test_verification_letter_has_ignore_note():
    """Получатель чужого кода не должен пугаться письма."""
    assert "игнорируйте" in core.build_verification_email_html("123456")


# --- сравнение адресов ---------------------------------------------------------


def test_is_same_email_case_and_spaces():
    assert core.is_same_email("Ivanov@Lib.ru", " ivanov@lib.ru ") is True


def test_is_same_email_different():
    assert core.is_same_email("a@lib.ru", "b@lib.ru") is False


def test_is_same_email_empty_is_false():
    """Пустая почта ничему не равна — в т.ч. другой пустой."""
    assert core.is_same_email(None, "") is False
    assert core.is_same_email("", "") is False


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


# --- регрессия UI (статически) --------------------------------------------------


def test_login_screen_mentions_admin_contact():
    """Экран входа говорит, куда обратиться за паролем (строкой, не
    кнопкой-мейлто). Проверяем статически: GUI в тестах не поднимаем."""
    assert "Не знаете пароль?" in MAIN_TEXT
    assert "mailto" not in MAIN_TEXT
    assert "Скопировать текст" not in MAIN_TEXT


def test_send_form_has_inline_confirmation():
    """Подтверждение почты автора — инлайн в форме: кнопка отправки кода
    и проверка кода без модальных окон."""
    assert "Подтвердить почту" in MAIN_TEXT
    assert "Проверить код" in MAIN_TEXT


def test_submit_blocked_until_email_confirmed():
    """Отправка не начинается с неподтверждённой почтой; verified_email
    меняется только успешной проверкой кода, не кнопкой «Отправить»."""
    assert "self._email_confirmed(email)" in MAIN_TEXT
    assert 'self.settings["verified_email"] = email' not in MAIN_TEXT


def test_admin_letter_reply_to_author():
    """Письмо администратору отвечает напрямую автору (Reply-To)."""
    assert "msg['Reply-To'] = payload['email']" in MAIN_TEXT


def test_branch_not_silently_prefilled():
    """Филиал по умолчанию — «Не указывать», а не первый из списка:
    тихий дефолт приписывал новости чужой филиал (v1.6.0)."""
    assert "BRANCH_NOT_SPECIFIED" in MAIN_TEXT
    assert "self.branches[0]" not in MAIN_TEXT
    assert '"last_branch": core.BRANCH_NOT_SPECIFIED' in MAIN_TEXT
