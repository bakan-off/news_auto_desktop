import re

import customtkinter as ctk

import theme

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_palettes_have_same_keys():
    assert set(theme.DARK) == set(theme.LIGHT)


def test_palette_values_are_hex():
    for palette in (theme.DARK, theme.LIGHT):
        for key, value in palette.items():
            assert HEX_COLOR.match(value), f"{key}: {value}"


def test_palette_for_dark_and_light():
    assert theme.palette_for("dark") is theme.DARK
    assert theme.palette_for("light") is theme.LIGHT


def test_palette_for_system_resolves():
    # без окна приложения должен вернуться один из двух словарей, а не KeyError
    assert theme.palette_for("system") in (theme.DARK, theme.LIGHT)


def test_labels_mapping():
    assert theme.APPEARANCE_LABELS["Тёмная"] == "dark"
    assert theme.APPEARANCE_LABELS["Светлая"] == "light"
    # «Системная» убрана по решению заказчика: только тёмная и светлая
    assert "Системная" not in theme.APPEARANCE_LABELS
    assert len(theme.APPEARANCE_LABELS) == 2
    # обратное отображение — для выставления выбранного значения переключателя
    assert theme.APPEARANCE_BY_MODE["dark"] == "Тёмная"


def test_current_follows_appearance_mode():
    ctk.set_appearance_mode("light")
    assert theme.current() is theme.LIGHT
    ctk.set_appearance_mode("dark")
    assert theme.current() is theme.DARK
