"""Палитры оформления: тёмная (основная) и светлая темы.

Правило: в виджетах main.py запрещены захардкоженные hex-цвета —
все берутся отсюда. Иначе светлая тема не сможет переключаться.

Режимы appearance_mode (в config.json): "dark" | "light".
Значение "system" из старых конфигов tolerated: разрешается через
фактически применённый режим.
"""
import customtkinter as ctk

# Подписи для переключателя в настройках -> режим
APPEARANCE_LABELS = {"Тёмная": "dark", "Светлая": "light"}
APPEARANCE_BY_MODE = {v: k for k, v in APPEARANCE_LABELS.items()}

DARK = {
    # фоны
    "bg": "#1a1c1e",            # окно и рабочая область
    "nav_bg": "#141618",        # боковая панель навигации
    "card": "#212529",          # карточки и боксы
    "chip": "#2d2f31",          # карточка прикреплённого файла
    "thumb_bg": "#1a1c1e",      # фон под миниатюрой
    "input_bg": "#2b2b2b",      # поля ввода
    # строки и границы
    "border": "#3a3d40",
    "text": "#ffffff",
    "text_secondary": "#adb5bd",
    "placeholder": "#808080",
    # акценты
    "accent": "#0d6efd",
    "accent_hover": "#0a58ca",
    "on_accent": "#ffffff",     # текст поверх акцентной заливки
    "success": "#2d8a4e",
    "success_hover": "#23713f",
    "danger": "#a33333",
    "danger_hover": "#ff4444",
    "error": "#ff4444",
    # hover для прозрачных/вторичных кнопок
    "card_hover": "#2d2f31",
    "hover_soft": "#2b2b2b",
}

LIGHT = {
    # фоны
    "bg": "#f4f5f7",
    "nav_bg": "#e9ebee",
    "card": "#ffffff",
    "chip": "#ffffff",
    "thumb_bg": "#eceef1",
    "input_bg": "#ffffff",
    # строки и границы
    "border": "#d4d8dd",
    "text": "#1f2328",
    "text_secondary": "#5c6670",
    "placeholder": "#98a0a8",
    # акценты
    "accent": "#0b5ed7",
    "accent_hover": "#0a58ca",
    "on_accent": "#ffffff",
    "success": "#1e7e34",
    "success_hover": "#19692c",
    "danger": "#b02a37",
    "danger_hover": "#8f2230",
    "error": "#d32f2f",
    # hover для прозрачных/вторичных кнопок
    "card_hover": "#e2e5e9",
    "hover_soft": "#e9ecef",
}


def palette_for(mode: str) -> dict:
    """Палитра для режима: 'dark' | 'light' | 'system'."""
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    # 'system' и любые другие значения: берём фактически применённый режим
    return current()


def current() -> dict:
    """Палитра для фактически применённого сейчас режима.

    ctk.get_appearance_mode() возвращает 'Light'/'Dark' — в том числе
    в режиме 'system' (разрешается через darkdetect при установке).
    """
    return LIGHT if str(ctk.get_appearance_mode()).lower() == "light" else DARK
