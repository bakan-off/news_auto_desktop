"""Смоук-тест: модуль main должен импортироваться без ошибок (GUI не запускается)."""


def test_main_importable():
    import main

    assert hasattr(main, "NewsApp")
    assert hasattr(main, "LoginWindow")
    assert hasattr(main, "CustomMessagebox")
