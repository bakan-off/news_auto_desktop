import json
import os
import shutil
import tempfile

import pytest

import core

DEFAULTS = {
    "appearance_mode": "dark",
    "hashtags": ["#КМЦБС", "#вбиблиотеке"],
    "verified_email": None,
    "last_branch": "Филиал 1",
    "drafts": [],
    "history": [],
    "webdav_login": "user",
}


@pytest.fixture()
def tmp_dir():
    """Каталог для временных файлов теста.

    Работает с прямыми путями (без перечисления содержимого каталогов),
    чтобы тесты не зависели от прав на scandir/listdir в окружении.
    """
    d = tempfile.mkdtemp(prefix="nad_cfg_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _config_path(tmp_dir: str) -> str:
    return os.path.join(tmp_dir, "config.json")


def test_merge_fills_missing_keys():
    assert core.merge_defaults({}, DEFAULTS) == DEFAULTS


def test_merge_keeps_saved_values_and_unknown_keys():
    saved = {"last_branch": "Филиал 2", "future_key": 42}
    merged = core.merge_defaults(saved, DEFAULTS)
    assert merged["last_branch"] == "Филиал 2"
    assert merged["future_key"] == 42
    assert merged["hashtags"] == DEFAULTS["hashtags"]


def test_merge_replaces_empty_strings_with_defaults():
    merged = core.merge_defaults({"last_branch": "   "}, DEFAULTS)
    assert merged["last_branch"] == DEFAULTS["last_branch"]


def test_merge_keeps_none_verified_email():
    # None — валидное состояние «выполнен выход», не должно затираться
    merged = core.merge_defaults({"verified_email": None}, DEFAULTS)
    assert merged["verified_email"] is None


def test_merge_repairs_broken_list_types():
    merged = core.merge_defaults({"hashtags": "#КМЦБС", "drafts": "oops"}, DEFAULTS)
    assert merged["hashtags"] == DEFAULTS["hashtags"]
    assert merged["drafts"] == []


def test_merge_ignores_non_dict_saved():
    assert core.merge_defaults(["not", "a", "dict"], DEFAULTS) == DEFAULTS


def test_load_missing_file_returns_defaults(tmp_dir):
    settings, backup = core.load_settings(_config_path(tmp_dir), DEFAULTS)
    assert settings == DEFAULTS
    assert backup is None


def test_load_valid_file_roundtrip(tmp_dir):
    path = _config_path(tmp_dir)
    saved = dict(DEFAULTS, last_branch="Филиал 9", verified_email="a@b.ru")
    core.save_settings(saved, path)
    settings, backup = core.load_settings(path, DEFAULTS)
    assert settings["last_branch"] == "Филиал 9"
    assert settings["verified_email"] == "a@b.ru"
    assert backup is None


def test_load_corrupt_file_backs_up_and_returns_defaults(tmp_dir):
    path = _config_path(tmp_dir)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{это не json")
    settings, backup = core.load_settings(path, DEFAULTS)
    assert settings == DEFAULTS
    assert backup is not None and os.path.exists(backup)
    with open(backup, encoding="utf-8") as f:
        assert f.read() == "{это не json"


def test_load_non_dict_json_returns_defaults(tmp_dir):
    path = _config_path(tmp_dir)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]")
    settings, backup = core.load_settings(path, DEFAULTS)
    assert settings == DEFAULTS
    assert backup is None


def test_save_is_atomic_and_valid_json(tmp_dir):
    path = _config_path(tmp_dir)
    core.save_settings(DEFAULTS, path)
    # временный файл заменён, а не остался рядом
    assert not os.path.exists(f"{path}.tmp")
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == DEFAULTS


def test_save_overwrites_previous(tmp_dir):
    path = _config_path(tmp_dir)
    core.save_settings(DEFAULTS, path)
    core.save_settings(dict(DEFAULTS, last_branch="Филиал 3"), path)
    settings, _ = core.load_settings(path, DEFAULTS)
    assert settings["last_branch"] == "Филиал 3"
