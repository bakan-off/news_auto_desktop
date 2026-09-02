import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
from urllib.error import HTTPError

import pytest

import core


@pytest.fixture(autouse=True)
def _cache_in_tmp(monkeypatch):
    """Кэш проверки обновлений — во временную папку теста, не в репозиторий.

    tempfile.mkdtemp вместо tmp_path pytest: создание pytest-of-<user>
    в песочнице падает с PermissionError.
    """
    tmpdir = tempfile.mkdtemp(prefix="nad_cache_")
    monkeypatch.setattr(core, "_update_cache_path",
                        lambda: os.path.join(tmpdir, ".update_cache.json"))
    yield
    shutil.rmtree(tmpdir, ignore_errors=True)

# --- Лимиты и валидация ------------------------------------------------------


def test_parse_version():
    assert core.parse_version("v1.2.3") == (1, 2, 3)
    assert core.parse_version("1.2.3") == (1, 2, 3)
    assert core.parse_version("2.0") == (2, 0)
    assert core.parse_version("v1.2.3-beta") is None
    assert core.parse_version("") is None
    assert core.parse_version("ветка") is None


def test_is_newer_version():
    assert core.is_newer_version("1.2.0", "1.1.9")
    assert core.is_newer_version("v2.0", "1.9.9")
    assert core.is_newer_version("1.2", "1.1.9")   # короткая версия дополняется нулями
    assert not core.is_newer_version("1.1.0", "1.1.0")
    assert not core.is_newer_version("1.0.9", "1.1.0")
    assert not core.is_newer_version("мусор", "1.0.0")


def test_no_automatic_update_check():
    """Автопроверки обновлений нет (v1.6.2) — только кнопка в настройках.

    Заказчик явно просил: программа не должна лезть в сеть сама. Регрессия
    на возврат тихого автозапуска после входа (v1.6.1 и раньше).
    """
    src = pathlib.Path(__file__).resolve().parent.parent / "main.py"
    text = src.read_text(encoding="utf-8")
    # после входа проверка не запускается
    assert "self.check_for_updates(silent=True)" not in text
    # у метода нет параметра silent — единственный вызов из кнопки
    assert "def check_for_updates(self, silent" not in text
    assert "check_for_updates(silent" not in text
    # кнопка в настройках остаётся и работает
    assert "command=self.check_for_updates_manual" in text


def test_validate_title_too_long():
    assert core.validate_submission("a@b.ru", "У" * 101, "текст", "Описание") is not None
    assert core.validate_submission("a@b.ru", "У" * 100, "текст", "Описание") is None


def test_validate_desc_too_long():
    assert core.validate_submission("a@b.ru", "Заголовок", "У" * 5001, "Описание") is not None
    assert core.validate_submission("a@b.ru", "Заголовок", "У" * 5000, "Описание") is None


def test_validate_files_too_heavy():
    d = tempfile.mkdtemp(prefix="nad_limits_")
    big = os.path.join(d, "big.bin")
    with open(big, "wb") as f:
        f.write(b"\0" * (1024 * 1024))  # 1 МБ
    try:
        # синтетический «тяжёлый» список: один файл, а размер завышаем,
        # подменяя getsize — проверяем формулу, а не диск
        real_getsize = os.path.getsize
        os.path.getsize = lambda p: 201 * 1024 * 1024
        try:
            err = core.validate_submission("a@b.ru", "Заголовок", "Текст", "Описание", files=[big])
            assert err is not None
            assert "МБ" in err
        finally:
            os.path.getsize = real_getsize
        # без подмены маленький файл проходит
        assert core.validate_submission("a@b.ru", "Заголовок", "Текст", "Описание", files=[big]) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_total_files_size_mb_missing_file_ok():
    assert core.total_files_size_mb([os.path.join(tempfile.gettempdir(), "nad_no_such_file.bin")]) == 0.0


# --- Ретраи -------------------------------------------------------------------


def test_with_retries_success_first_try():
    calls = []

    def op():
        calls.append(1)
        return "ок"

    assert core.with_retries(op, attempts=3, delay_sec=0) == "ок"
    assert len(calls) == 1


def test_with_retries_recovers():
    calls = []

    def op():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("сбой")
        return 42

    assert core.with_retries(op, attempts=5, delay_sec=0) == 42
    assert len(calls) == 3


def test_with_retries_raises_last_error():
    def op():
        raise TimeoutError("таймаут")

    try:
        core.with_retries(op, attempts=2, delay_sec=0)
    except TimeoutError as e:
        assert str(e) == "таймаут"
    else:
        raise AssertionError("должно было подняться исключение")


# --- Проверка обновлений --------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def read(self, n=-1):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _atom_feed(*tags: str) -> bytes:
    """Лента tags.atom с заданными тегами (как её отдаёт сайт GitHub)."""
    entries = "".join(f"<entry><title>{t}</title></entry>" for t in tags)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>repo: Tags</title>{entries}</feed>"
    ).encode()


def test_fetch_latest_version(monkeypatch):
    monkeypatch.setattr(core, "urlopen",
                        lambda req, timeout=1: _FakeResponse(_atom_feed("v1.0.0", "v1.1.0", "v0.9.0")))
    assert core.fetch_latest_version() == "1.1.0"


def test_fetch_latest_version_ignores_nonversion_titles(monkeypatch):
    """Непонятные записи ленты (nightly, «Tags») не ломают поиск версии."""
    monkeypatch.setattr(core, "urlopen",
                        lambda req, timeout=1: _FakeResponse(_atom_feed("nightly-build", "v1.3.1")))
    assert core.fetch_latest_version() == "1.3.1"


def test_fetch_latest_version_ascii_headers(monkeypatch):
    """User-Agent обязан кодироваться в latin-1: кириллица в заголовке
    рушила проверку обновлений (UnicodeEncodeError)."""
    captured = {}

    def fake_urlopen(req, timeout=1):
        captured["ua"] = req.get_header("User-agent")
        return _FakeResponse(_atom_feed("v1.0.0"))

    monkeypatch.setattr(core, "urlopen", fake_urlopen)
    assert core.fetch_latest_version() == "1.0.0"
    assert captured["ua"] == captured["ua"].encode("latin-1").decode("latin-1")
    assert "KMCBS" in captured["ua"]


def test_fetch_latest_version_no_tags(monkeypatch):
    monkeypatch.setattr(core, "urlopen", lambda req, timeout=1: _FakeResponse(_atom_feed()))
    assert core.fetch_latest_version() is None


def test_fetch_latest_version_uses_atom_feed_url(monkeypatch):
    """Проверка идёт в веб-ленту тегов основного репозитория, а не в
    api.github.com (лимиты API на общий офисный IP исчерпываются)."""
    urls = []
    monkeypatch.setattr(core, "urlopen",
                        lambda req, timeout=1: urls.append(req.full_url) or _FakeResponse(_atom_feed("v1.0.0")))
    core.fetch_latest_version()
    assert urls == ["https://github.com/bakan-off/news_auto_desktop/tags.atom"]


def test_fetch_latest_version_network_error(monkeypatch):
    def boom(req, timeout=1):
        raise OSError("нет сети")

    monkeypatch.setattr(core, "urlopen", boom)
    assert core.fetch_latest_version() is None


def test_fetch_latest_version_saves_etag_cache(monkeypatch):
    """Успешная проверка пишет кэш: etag + версия + время."""
    monkeypatch.setattr(core, "urlopen",
                        lambda req, timeout=1: _FakeResponse(_atom_feed("v2.0.0"),
                                                             headers={"ETag": 'W/"abc123"'}))
    assert core.fetch_latest_version() == "2.0.0"
    with open(core._update_cache_path(), encoding="utf-8") as f:
        cache = json.load(f)
    assert cache["etag"] == 'W/"abc123"'
    assert cache["latest"] == "2.0.0"
    assert cache["checked_at"] <= time.time()


def test_fetch_latest_version_304_reuses_cache(monkeypatch):
    """304 «не изменилось» не расходует лимит GitHub: версия из кэша."""
    core._save_update_cache({"etag": 'W/"x1"', "latest": "1.3.0", "checked_at": time.time()})
    requests = []

    def fake_urlopen(req, timeout=1):
        requests.append(req)
        raise HTTPError(req.full_url, 304, "Not Modified", None, None)

    monkeypatch.setattr(core, "urlopen", fake_urlopen)
    assert core.fetch_latest_version() == "1.3.0"
    # повторный запрос обязан нести If-None-Match из кэша
    assert requests[0].get_header("If-none-match") == 'W/"x1"'


def test_fetch_latest_version_rate_limit_falls_back_to_cache(monkeypatch):
    """403 (лимит анонимных запросов исчерпан) — отдаём свежий кэш,
    а не «не удалось проверить»."""
    core._save_update_cache({"etag": 'W/"x1"', "latest": "1.3.0", "checked_at": time.time()})

    def fake_urlopen(req, timeout=1):
        raise HTTPError(req.full_url, 403, "rate limit exceeded", None, None)

    monkeypatch.setattr(core, "urlopen", fake_urlopen)
    assert core.fetch_latest_version() == "1.3.0"


def test_fetch_latest_version_stale_cache_and_no_network(monkeypatch):
    """Кэш протух и сети нет — честный None (не подсовываем древнюю версию)."""
    core._save_update_cache({"etag": 'W/"x1"', "latest": "1.3.0",
                             "checked_at": time.time() - core.UPDATE_CACHE_TTL_SEC - 1})

    def boom(req, timeout=1):
        raise OSError("нет сети")

    monkeypatch.setattr(core, "urlopen", boom)
    assert core.fetch_latest_version() is None


def test_fetch_latest_version_corrupt_cache_ignored(monkeypatch):
    """Битый кэш не должен ломать проверку — просто проверяем по сети."""
    with open(core._update_cache_path(), "w", encoding="utf-8") as f:
        f.write("{не json")
    monkeypatch.setattr(core, "urlopen", lambda req, timeout=1: _FakeResponse(_atom_feed("v1.5.0")))
    assert core.fetch_latest_version() == "1.5.0"


# --- Секреты (Credential Manager) ----------------------------------------------


def test_migrate_secrets(monkeypatch):
    saved = {}

    monkeypatch.setattr(core, "store_secret", lambda key, value: saved.update({key: value}) or True)
    monkeypatch.setattr(core, "_cred_manager_available", lambda: True)

    settings = {"webdav_password": "w-secret", "smtp_password": "s-secret", "webdav_login": "user"}
    assert core.migrate_secrets_to_cred_manager(settings) is True
    assert saved == {"webdav_password": "w-secret", "smtp_password": "s-secret"}
    # из config.json пароли исчезли
    assert settings["webdav_password"] == "" and settings["smtp_password"] == ""
    # логин и прочие ключи не тронуты
    assert settings["webdav_login"] == "user"


def test_migrate_secrets_nothing_to_do(monkeypatch):
    monkeypatch.setattr(core, "store_secret", lambda key, value: True)
    monkeypatch.setattr(core, "_cred_manager_available", lambda: True)
    settings = {"webdav_password": "", "smtp_password": ""}
    assert core.migrate_secrets_to_cred_manager(settings) is False


def test_secret_roundtrip_win32():
    if sys.platform != "win32":
        return
    key = "test_probe_проверка"
    try:
        assert core.store_secret(key, "пароль-123") is True
        assert core.load_secret(key) == "пароль-123"
    finally:
        core.delete_secret(key)
    assert core.load_secret(key) is None


def test_resource_path_dev_mode():
    # в dev-режиме (не frozen) ресурс ищется рядом с кодом
    p = core.resource_path("app.ico")
    assert p == os.path.join(core.app_dir(), "app.ico")
