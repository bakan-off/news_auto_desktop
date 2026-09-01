import re

import core


def test_verification_code_format():
    code = core.generate_verification_code()
    assert isinstance(code, str)
    assert re.fullmatch(r"\d{6}", code)


def test_verification_code_varies():
    # фиксированный seed (как у random) дал бы одинаковые коды
    codes = {core.generate_verification_code() for _ in range(50)}
    assert len(codes) > 1


def test_security_policy_constants_sane():
    assert core.VERIFICATION_CODE_TTL_SEC >= 60
    assert core.VERIFICATION_CODE_MAX_ATTEMPTS >= 1
    assert core.SMTP_TIMEOUT_SEC >= 5


def test_pin_code_removed():
    # общий PIN-код входа удалён: он зашивался в exe и не останавливал
    # постороннего, идентификация — подтверждением рабочей почты
    assert not hasattr(core, "PIN_MAX_ATTEMPTS")
    assert not hasattr(core, "PIN_LOCKOUT_SEC")
