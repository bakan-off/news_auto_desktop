# Аннотации типов ленивые (строками): main.py собирается и под Python 3.8 —
# 32-битная legacy-сборка для Windows 7 / 32-битной Windows 10 (см. DEVELOPMENT.md)
from __future__ import annotations

import datetime
import logging
import os
import queue
import smtplib
import sys
import threading
import time
import webbrowser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler
from tkinter import filedialog

import customtkinter as ctk
from webdav3.client import Client

import core
import theme

# Попытка использовать windnd для Windows Drag & Drop
try:
    import windnd
    WINDND_AVAILABLE = True
except ImportError:
    WINDND_AVAILABLE = False

# Миниатюры прикреплённых изображений (Pillow); без него — карточки без превью
try:
    from PIL import Image, ImageOps
    THUMBNAILS_AVAILABLE = True
except ImportError:
    THUMBNAILS_AVAILABLE = False

log = logging.getLogger("news_app")

class CustomMessagebox(ctk.CTkToplevel):
    def __init__(self, parent, title, message, is_error=False):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x200")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (400 // 2)
        y = (self.winfo_screenheight() // 2) - (200 // 2)
        self.geometry(f"+{x}+{y}")
        
        p = theme.current()
        self.configure(fg_color=p["bg"])
        try:
            self.grab_set()  # блокирует основное окно; на скрытом окне может кинуть TclError
        except Exception:
            log.debug("grab_set в сообщении не сработал", exc_info=True)

        color = p["error"] if is_error else p["success"]

        ctk.CTkLabel(self, text=title, font=("Segoe UI", 20, "bold"), text_color=color).pack(pady=(20, 10))
        ctk.CTkLabel(self, text=message, font=("Segoe UI", 15), text_color=p["text"], wraplength=350, justify="center").pack(pady=10)

        ctk.CTkButton(self, text="ОК", width=120, height=40, font=("Segoe UI", 15), fg_color=p["card"], hover_color=p["card_hover"], border_width=1, text_color=p["text"], command=self.destroy).pack(pady=20)

class CustomYesNoBox(ctk.CTkToplevel):
    def __init__(self, parent, title, message, yes_text="Да", no_text="Нет"):
        super().__init__(parent)
        self.result = False
        self.title(title)
        self.geometry("500x250")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.winfo_screenheight() // 2) - (250 // 2)
        self.geometry(f"+{x}+{y}")
        
        p = theme.current()
        self.configure(fg_color=p["bg"])
        try:
            self.grab_set()
        except Exception:
            log.debug("grab_set в диалоге не сработал", exc_info=True)

        ctk.CTkLabel(self, text=title, font=("Segoe UI", 20, "bold"), text_color=p["accent"]).pack(pady=(20, 10))
        ctk.CTkLabel(self, text=message, font=("Segoe UI", 15), text_color=p["text"], wraplength=450, justify="center").pack(pady=10)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=10)

        ctk.CTkButton(btn_frame, text=yes_text, width=150, height=40, font=("Segoe UI", 14), fg_color=p["danger"], hover_color=p["danger_hover"], command=self.on_yes).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text=no_text, width=150, height=40, font=("Segoe UI", 14), fg_color=p["card"], hover_color=p["card_hover"], border_width=1, text_color=p["text"], command=self.on_no).pack(side="left", padx=10)

    def on_yes(self):
        self.result = True
        self.destroy()

    def on_no(self):
        self.result = False
        self.destroy()

    def get_result(self):
        self.wait_window()
        return self.result

class LoginWindow(ctk.CTkToplevel):
    """Вход: почта получателя + пароль облачного аккаунта (v1.5.0).

    Кода подтверждения больше нет: пароль — единственный барьер (секретов
    в программе нет, пароль выдаёт владелец лично). Ошибки показываются
    строкой под полем — без модальных окон и вспомогательных экранов.
    """

    def __init__(self, parent, on_success):
        super().__init__(parent)
        self.parent = parent
        self.on_success = on_success
        self.title("Вход — КМЦБС Новости")
        self.geometry("440x430")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        # Защита от перебора: после 5 неудач — минутная пауза
        # (повторные неверные логины могут надолго заблокировать
        # общий аккаунт на стороне mail.ru)
        self._attempts = 0
        self._lock_until = 0.0

        # Центрирование
        self.update_idletasks()
        w, h = 440, 430
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

        # B4: закрытие окна входа крестиком должно завершать приложение,
        # иначе оно навсегда зависало в памяти скрытым
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        ctk.CTkLabel(self, text="Добро пожаловать!", font=("Segoe UI", 22, "bold")).pack(pady=(28, 4))
        ctk.CTkLabel(self, text="Программа для отправки новостей КМЦБС",
                     font=("Segoe UI", 12), text_color=theme.current()["text_secondary"]).pack()

        ctk.CTkLabel(self, text="Почта получателя новостей:", font=("Segoe UI", 12, "bold")).pack(pady=(14, 2))
        self.entry_admin = ctk.CTkEntry(self, width=310, height=40, font=("Segoe UI", 14))
        self.entry_admin.pack()
        self.entry_admin.insert(0, self.parent.settings.get("admin_email") or "")

        ctk.CTkLabel(self, text="Пароль:", font=("Segoe UI", 12, "bold")).pack(pady=(12, 2))
        self.entry_pw = ctk.CTkEntry(self, width=310, height=40, show="*", font=("Segoe UI", 14))
        self.entry_pw.pack()
        self.entry_pw.focus_set()
        self.entry_pw.bind("<Return>", lambda _e: self.try_login())

        self._show_pw = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Показать пароль", variable=self._show_pw, font=("Segoe UI", 11),
                        checkbox_width=18, checkbox_height=18, command=self._toggle_pw).pack(pady=(8, 0))

        self.btn_login = ctk.CTkButton(self, text="Войти", width=200, height=42, command=self.try_login,
                                       fg_color=theme.current()["success"], hover_color=theme.current()["success_hover"])
        self.btn_login.pack(pady=(16, 2))

        # Инлайн-ошибка вместо модальных окон
        self.error_label = ctk.CTkLabel(self, text="", font=("Segoe UI", 12),
                                        text_color=theme.current()["error"], wraplength=330, justify="center")
        self.error_label.pack(pady=(4, 0))

        ctk.CTkLabel(self, text="Не знаете пароль? Напишите: "
                                f"{self.parent.settings.get('admin_email') or 'администратору'}",
                     font=("Segoe UI", 11), text_color=theme.current()["text_secondary"]).pack(side="bottom", pady=16)

    def on_close(self):
        self.parent.destroy()

    def _toggle_pw(self):
        self.entry_pw.configure(show="" if self._show_pw.get() else "*")

    def _show_error(self, text: str):
        self.error_label.configure(text=text)

    def try_login(self):
        if time.monotonic() < self._lock_until:
            left = int(self._lock_until - time.monotonic()) + 1
            self._show_error(f"Слишком много попыток — подождите {left} с.")
            return
        admin = self.entry_admin.get().strip()
        password = self.entry_pw.get().strip()
        if not core.is_valid_email(admin):
            self._show_error("Укажите корректную почту получателя.")
            return
        if not password:
            self._show_error("Введите пароль.")
            return

        self._show_error("")
        self.btn_login.configure(state="disabled", text="Проверяю...")
        threading.Thread(target=self._check_credentials, args=(admin, password), daemon=True).start()

    def _check_credentials(self, admin: str, password: str):
        """Проверяет пароль реальным SMTP-логином (в фоновом потоке)."""
        try:
            with smtplib.SMTP_SSL(self.parent.settings["smtp_server"],
                                  self.parent.settings["smtp_port"],
                                  timeout=core.SMTP_TIMEOUT_SEC) as server:
                server.login(self.parent.settings["smtp_user"], password)

            def accepted():
                # аккаунт программы один: пароль подходит и для почты, и для облака
                self.parent.settings["admin_email"] = admin
                self.parent.settings["smtp_password"] = password
                self.parent.settings["webdav_password"] = password
                self.parent.save_settings()
                self.on_success()
                self.destroy()

            # UI — только через очередь главного окна: self.after из
            # фонового потока может обрушить Tcl (правило B4)
            self.parent.ui_post(accepted)
        except Exception as e:
            auth_failed = core.is_auth_error(e)
            log.warning("Не удалось войти: %s", e)

            def rejected():
                self.btn_login.configure(state="normal", text="Войти")
                if not auth_failed:
                    self._show_error("Не удалось связаться с почтовым сервером.\n"
                                     "Проверьте интернет и попробуйте ещё раз.")
                    return
                self._attempts += 1
                self.entry_pw.delete(0, "end")
                self.entry_pw.focus_set()
                if self._attempts >= core.LOGIN_MAX_ATTEMPTS:
                    self._lock_until = time.monotonic() + core.LOGIN_LOCKOUT_SEC
                    self._attempts = 0
                    self._show_error("Пароль не подошёл.\nПодождите минуту и попробуйте снова.")
                else:
                    self._show_error("Пароль не подошёл. Проверьте его\nили запросите у администратора.")

            self.parent.ui_post(rejected)


class NewsApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Паролей в коде НЕТ: облачный пароль выдаётся администратором лично
        # и вводится один раз на экране входа (хранится в Windows
        # Credential Manager). Общий пароль один — от аккаунта
        # muk_kmcbs_smi@mail.ru (облако и почта).
        self.defaults = {
            "webdav_url": "https://webdav.cloud.mail.ru",
            "webdav_login": "muk_kmcbs_smi@mail.ru",
            "webdav_password": "",
            "smtp_server": "smtp.mail.ru",
            "smtp_port": 465,
            "smtp_user": "muk_kmcbs_smi@mail.ru",
            "smtp_password": "",
            "admin_email": "muk_kmcbs_smi@mail.ru"
        }

        self.branches = [
            "Куминская библиотека-филиал №1", "Леушинская библиотека-филиал №2 имени Нины Викторовны Лангенбах",
            "Междуреченская детская библиотека-филиал №4", "Луговская библиотека-филиал №5",
            "Морткинская библиотека-филиал №6", "Половинкинская библиотека филиал №7",
            "Алтайская библиотека филиал №8", "Болчаровская библиотека-филиал №9",
            "Мулымская модельная библиотека-филиал № 10", "Лиственичная библиотека-филиал № 11",
            "Чантырская библиотека-филиал №12", "Шугурская библиотека-филиал №13",
            "Юмасинская библиотека - филиал №14", "Ягодинская библиотека-филиал №15 имени А. М. Коньковой",
            "Ямкинская библиотека-филиал №16", "Назаровская библиотека-филиал №17",
            "Междуреченская библиотека-филиал №18", "Ушьинская библиотека-филиал №19",
            "Кондинская библиотека-филиал №20", "Кондинская библиотека-филиал №21",
            "Камская библиотека-филиал №22", "Отдел обслуживания Центральной библиотеки им. А.С. Тарханова",
            "Общественно-информационный центр библиотеки им. А.С. Тарханова", "Информационно-библиографический сектор библиотеки им. А.С. Тарханова",
            "Сектор эколого-краеведческой литературы библиотеки им. А.С. Тарханова", "Сектор искусства библиотеки им. А.С. Тарханова",
            "Центр общественного доступа библиотеки им. А.С. Тарханова", "Охрана труда библиотеки им. А.С. Тарханова",
            "Отдел материально-технического обеспечения библиотеки им. А.С. Тарханова", "Отдел комплектования фонда библиотеки им. А.С. Тарханова",
            "Отдел методической деятельности библиотеки им. А.С. Тарханова"
        ]

        self.social_links = {
            "Сайт": "https://kondinskaya-mcbs.gosuslugi.ru",
            "ВК": "https://vk.com/mukmcbs", "ОК": "https://ok.ru/mukmcbs",
            "Max": "https://max.ru/id8616009661_gos", "Telegram": "https://t.me/mukkmcbs"
        }

        # config.json лежит рядом с приложением, а не в текущей рабочей папке запуска
        self.config_path = os.path.join(core.app_dir(), "config.json")
        self.load_settings()

        self.title("КМЦБС Новости")
        self.geometry("1200x900")
        self.minsize(1000, 850)
        self.withdraw()
        self.protocol("WM_DELETE_WINDOW", self.on_close_app)

        # Иконка окна (в сборке лежит рядом с exe, в dev — в корне проекта)
        try:
            icon_path = core.resource_path("app.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            log.debug("Иконка окна не установлена", exc_info=True)
        
        ctk.set_appearance_mode(self.settings.get("appearance_mode", "dark"))
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=theme.current()["bg"])

        self.main_font = ("Segoe UI", 15)
        self.field_label_font = ("Segoe UI", 12, "bold")
        self.header_font = ("Segoe UI", 32, "bold")
        self.sub_header_font = ("Segoe UI", 20, "bold")

        self.selected_files = []
        self.placeholder_text = "Описание"
        self.current_tag_widgets = []
        self.age_rating = "0+"
        self._sending = False
        self._resize_job = None
        self._thumb_cache = {}
        self._ui_queue = queue.Queue()

        self.grid_columnconfigure(0, weight=0, minsize=240)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.navigation_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=theme.current()["nav_bg"])
        self.navigation_frame.grid(row=0, column=0, sticky="nsew")
        self.navigation_frame.grid_columnconfigure(0, weight=1)
        self.navigation_frame.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self.navigation_frame, text="КМЦБС\nНовости", font=("Segoe UI", 24, "bold")).grid(row=0, column=0, padx=20, pady=50)

        self.btn_send = self.create_nav_btn("Отправить новость", self.show_send_frame, 1)
        self.btn_drafts = self.create_nav_btn("Черновики", self.show_drafts_frame, 2)
        self.btn_history = self.create_nav_btn("История", self.show_history_frame, 3)
        self.btn_settings = self.create_nav_btn("Настройки", self.show_settings_frame, 4)

        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color=theme.current()["bg"], corner_radius=0)
        self.main_scroll.grid(row=0, column=1, padx=0, pady=0, sticky="nsew")
        self.main_scroll.columnconfigure(0, weight=1)

        self.main_container = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        self.main_container.grid(row=0, column=0, padx=60, pady=30, sticky="nsew")
        self.main_container.columnconfigure(0, weight=1)

        self.show_send_frame()
        self.bind("<Configure>", self.on_window_resize)
        self.bind("<Key>", self.handle_global_hotkeys)
        # Цикл обработки очереди UI-обновлений из фоновых потоков.
        # Прямые вызовы self.after() из потока — известная причина аварий
        # Tcl (Tcl_AsyncDelete) и вылетов приложения.
        self.after(80, self._poll_ui_queue)

        if WINDND_AVAILABLE:
            try:
                windnd.hook_dropfiles(self, self.handle_windnd_drop)
            except Exception:
                log.warning("Не удалось включить Drag&Drop (windnd)", exc_info=True)

        if (self.settings.get("smtp_password") or "").strip():
            # пароль уже сохранён на этой машине (Credential Manager) —
            # сразу в программу; почта автора указывается в форме отправки.
            # Через after(): deiconify/zoomed должны выполняться при
            # работающем mainloop, иначе окно остаётся скрытым
            self.after(50, self.on_login_success)
        else:
            # пароль ещё не вводился — единственный экран входа
            # (почта получателя + пароль, без кодов подтверждения)
            self.login_win = LoginWindow(self, self.on_login_success)

    @property
    def palette(self) -> dict:
        """Активная палитра (тёмная/светлая) — по фактически применённому режиму.

        Свойство, а не поле: страницы читают его при каждой отрисовке,
        поэтому переключение темы обновляет их без храненых ссылок.
        """
        return theme.current()

    @property
    def accent_blue(self) -> str:
        return self.palette["accent"]

    def _apply_palette(self):
        """Перекрашивает статичные элементы (фон окна, боковая панель, кнопки навигации).

        Вызывается при каждой смене страницы: навигация создаётся один раз
        при старте, и без этого осталась бы со цветами стартовой темы.
        """
        p = self.palette
        self.configure(fg_color=p["bg"])
        self.navigation_frame.configure(fg_color=p["nav_bg"])
        self.main_scroll.configure(fg_color=p["bg"])
        for btn in (self.btn_send, self.btn_drafts, self.btn_history, self.btn_settings):
            btn.configure(border_color=p["border"], text_color=p["text"], hover_color=p["card_hover"])

    def on_close_app(self):
        """Закрытие главного окна: автосохранение незавершённой новости.

        Если форма «Отправить новость» заполнена (заголовок/описание/файлы),
        содержимое молча сохраняется в черновики — набранное не теряется.
        Во время отправки окно закрыть нельзя (фоновый поток пишет в облако).
        """
        if self._sending:
            CustomMessagebox(self, "Идёт отправка",
                             "Новость ещё отправляется. Дождитесь завершения — окно закроется само.",
                             is_error=True)
            return
        try:
            on_form = hasattr(self, "entry_title") and self.entry_title.winfo_exists()
            if on_form:
                payload = self._collect_payload()
                has_content = (payload["title"]
                               or (payload["desc"] and payload["desc"] != self.placeholder_text)
                               or payload["files"])
                if has_content:
                    self._save_draft_from_payload(payload)
        except Exception:
            log.exception("Ошибка автосохранения при закрытии")
        self.destroy()

    def _poll_ui_queue(self):
        """Исполняет функции, поставленные в очередь фоновыми потоками.

        Очередь опрашивается только в главном потоке — это единственный
        потокобезопасный способ обновлять UI из фоновых потоков.
        """
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                log.exception("Ошибка в отложенном обновлении UI")
        if self.winfo_exists():
            self.after(80, self._poll_ui_queue)

    def ui_post(self, fn):
        """Просит главный поток выполнить fn (безопасно из любого потока)."""
        self._ui_queue.put(fn)

    def report_callback_exception(self, exc, val, tb):
        """Ошибки в колбэках Tk — в лог, а не в никуда.

        В оконной сборке exe stderr отсутствует, и без этого перехвата
        причины сбоев интерфейса невозможно диагностировать.
        """
        log.error("Необработанное исключение в колбэке Tk", exc_info=(exc, val, tb))

    def on_login_success(self):
        # Форма «Отправить новость» перерисовывается: поле «Ваш Email»
        # должно показать почту автора из прошлой сессии
        self.show_send_frame()
        self.deiconify()
        self.state("zoomed")
        # Проверка обновлений НЕ запускается сама (v1.6.2): только по кнопке
        # в настройках — по требованию заказчика
        if getattr(self, "_config_warning", None):
            warning, self._config_warning = self._config_warning, None
            self.after(300, lambda: CustomMessagebox(self, "Внимание", warning))

    def check_for_updates(self):
        """Сверяет версию с тегами публичного репозитория (в фоне).

        Запускается ТОЛЬКО кнопкой «Проверить обновления» в настройках
        (v1.6.2): автопроверки после входа больше нет.
        Нет сети / репозиторий недоступен — честно сообщает об этом.
        Повторные нажатия, пока идёт проверка, игнорируются: раньше каждый
        клик рождал свой поток и своё окно результата.
        """
        if getattr(self, "_update_check_busy", False):
            return
        self._update_check_busy = True
        if getattr(self, "btn_check_updates", None) and self.btn_check_updates.winfo_exists():
            self.btn_check_updates.configure(state="disabled", text="Проверяю...")

        def worker():
            latest = core.fetch_latest_version()

            def report():
                if getattr(self, "btn_check_updates", None) and self.btn_check_updates.winfo_exists():
                    self.btn_check_updates.configure(state="normal", text="Проверить обновления")
                self._update_check_busy = False
                if latest and core.is_newer_version(latest, core.APP_VERSION):
                    dialog = CustomYesNoBox(
                        self, "Доступно обновление",
                        f"Вышла новая версия: {latest} (у вас {core.APP_VERSION}).\n\n"
                        f"Открыть страницу загрузки?",
                        yes_text="Открыть страницу", no_text="Позже")
                    if dialog.get_result():
                        webbrowser.open(f"https://github.com/{core.GITHUB_REPO}/releases")
                else:
                    if latest:
                        CustomMessagebox(self, "Обновления",
                                         f"У вас последняя версия: {core.APP_VERSION}.")
                    else:
                        CustomMessagebox(self, "Обновления",
                                         f"Не удалось проверить обновления — сеть или GitHub "
                                         f"сейчас недоступны.\n\n"
                                         f"Попробуйте позже.\n"
                                         f"Текущая версия: {core.APP_VERSION}.")

            # через очередь — не self.after из потока (причина вылетов Tcl)
            self.ui_post(report)

        threading.Thread(target=worker, daemon=True).start()

    def handle_global_hotkeys(self, event):
        # Хак для не-латинских раскладок (рус.): Ctrl+C/V/X/A в Tk штатно
        # не срабатывают, т.к. биндинги привязаны к латинским keysym.
        # На латинской раскладке событие пропускаем — его обрабатывают
        # стандартные биндинги Tk (иначе возможна двойная вставка, B12).
        if not (event.state & 0x0004):
            return
        if str(event.keysym).lower() in ("v", "c", "a", "x"):
            return
        try:
            w = self.focus_get()
            if not w: return
            if event.keycode == 86: w.event_generate("<<Paste>>")
            elif event.keycode == 67: w.event_generate("<<Copy>>")
            elif event.keycode == 65: w.event_generate("<<SelectAll>>")
            elif event.keycode == 88: w.event_generate("<<Cut>>")
            else: return
            return "break"
        except Exception:
            log.debug("Ошибка обработки горячей клавиши", exc_info=True)

    def create_nav_btn(self, text, command, row):
        btn = ctk.CTkButton(self.navigation_frame, text=text, width=200, height=50, corner_radius=10,
                            font=self.main_font, command=command, fg_color="transparent", border_width=1,
                            border_color=theme.current()["border"], text_color=theme.current()["text"],
                            hover_color=theme.current()["card_hover"])
        btn.grid(row=row, column=0, pady=10)
        return btn

    def load_settings(self):
        default_settings = {
            "appearance_mode": "dark",
            "hashtags": ["#КМЦБС", "#вбиблиотеке"],
            "verified_email": None,
            "last_branch": core.BRANCH_NOT_SPECIFIED,
            "drafts": [],
            "history": []
        }
        default_settings.update(self.defaults)
        self.settings, backup = core.load_settings(self.config_path, default_settings)
        # Пароли: из config.json в Windows Credential Manager (значения не меняются).
        # При сбое диспетчера всё остаётся работать как раньше — из config.json.
        if core.migrate_secrets_to_cred_manager(self.settings):
            # фиксируем config.json уже без паролей, потом наполняем из диспетчера
            core.save_settings(self.settings, self.config_path)
        for key in core.SECRET_KEYS:
            if not self.settings.get(key):
                value = core.load_secret(key)
                if value:
                    self.settings[key] = value
        self._config_warning = (
            f"Файл настроек был повреждён и восстановлен по умолчанию.\n"
            f"Копия старого файла сохранена: {backup}"
            if backup else None
        )

    def save_settings(self):
        # Пароли хранятся в Credential Manager, а не в config.json:
        # в файл попадают только если диспетчер недоступен (откат)
        to_save = dict(self.settings)
        for key in core.SECRET_KEYS:
            value = (to_save.get(key) or "").strip()
            if value and core.store_secret(key, value):
                to_save[key] = ""
        core.save_settings(to_save, self.config_path)

    def clear_main_container(self):
        for widget in self.main_container.winfo_children(): widget.destroy()
        self.current_tag_widgets = []

    def on_window_resize(self, event):
        if event.widget is not self:
            return
        # B13: дебаунс — при ресайзе Tk присылает десятки событий,
        # пересчёт раскладки тегов выполняем один раз после паузы
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(120, self.rearrange_active_tags)

    def rearrange_active_tags(self):
        self._resize_job = None
        if not self.current_tag_widgets: return
        self.update_idletasks()
        w = self.main_scroll.winfo_width() - 150 
        if w < 200: w = 800
        cols = max(1, w // 160)
        for i, widget in enumerate(self.current_tag_widgets):
            if widget.winfo_exists(): widget.grid(row=i // cols, column=i % cols, padx=5, pady=5, sticky="w")

    def show_send_frame(self):
        self.clear_main_container()
        self._apply_palette()
        ctk.CTkLabel(self.main_container, text="Публикация новостей", font=self.header_font).grid(row=0, column=0, pady=(0, 40))

        # Почта автора: подтверждается прямо в форме (код на почту,
        # один раз до её смены) — администратор отвечает на настоящий
        # адрес. Статус и ввод кода — строкой под полем, без модалок
        email_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        email_frame.grid(row=1, column=0, sticky="ew", pady=(5, 10))
        email_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(email_frame, text="Ваш Email (автор новости)", font=self.field_label_font, text_color=self.palette["text_secondary"]).grid(row=0, column=0, sticky="w")
        self.entry_email = ctk.CTkEntry(email_frame, height=45, font=self.main_font, fg_color=self.palette["input_bg"], border_width=1, border_color=self.palette["border"], placeholder_text="vasha@rabota.ru")
        self.entry_email.insert(0, str(self.settings.get("verified_email") or ""))
        self.entry_email.grid(row=1, column=0, pady=(5, 0), sticky="ew")
        self.entry_email.bind("<KeyRelease>", lambda _e: self._on_email_changed())
        self.email_status_frame = ctk.CTkFrame(email_frame, fg_color="transparent")
        self.email_status_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        # состояние подтверждения почты (см. _render_email_status)
        self._vcode = None
        self._vcode_email = None
        self._vcode_expires = 0.0
        self._vcode_attempts = 0
        self._vcode_sent_at = 0.0
        self._email_msg = None
        self._email_sending = False
        self._email_ui_state = None
        self._render_email_status()
        
        ctk.CTkLabel(self.main_container, text="Филиал или отдел", font=self.field_label_font, text_color=self.palette["text_secondary"]).grid(row=3, column=0, sticky="w", pady=(5,0))
        # «Не указывать» первой строкой: филиал НЕ подставляется сам —
        # тихий дефолт приписывал новости чужой филиал. Помнится только
        # осознанный выбор сотрудника (last_branch)
        self.branch_values = [core.BRANCH_NOT_SPECIFIED, *self.branches]
        self.branch_opt = ctk.CTkOptionMenu(self.main_container, values=self.branch_values, height=45, font=self.main_font, dropdown_font=self.main_font)
        last = self.settings.get("last_branch")
        self.branch_opt.set(last if last in self.branch_values else core.BRANCH_NOT_SPECIFIED)
        self.branch_opt.grid(row=4, column=0, pady=(5, 15), sticky="ew")

        self.entry_title = self.create_styled_entry("Название новости", 5)
        self.title_counter = ctk.CTkLabel(self.main_container, text="", font=("Segoe UI", 11), text_color=self.palette["text_secondary"])
        self.title_counter.grid(row=6, column=0, sticky="e", pady=(0, 2))
        self.entry_title.bind("<KeyRelease>", lambda e: self._update_title_counter())

        age_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        age_frame.grid(row=7, column=0, pady=10, sticky="w")
        ctk.CTkLabel(age_frame, text="Возрастной ценз", font=self.field_label_font, text_color=self.palette["text_secondary"]).pack(side="left", padx=(0, 15))
        for r in ["0+", "6+", "12+", "16+", "18+"]:
            btn = ctk.CTkButton(age_frame, text=r, width=60, height=35, corner_radius=5, font=self.main_font,
                                border_width=1, border_color=self.accent_blue if r == self.age_rating else self.palette["border"],
                                fg_color=self.accent_blue if r == self.age_rating else "transparent",
                                text_color=self.palette["on_accent"] if r == self.age_rating else self.palette["text_secondary"],
                                hover_color=self.palette["accent_hover"],
                                command=lambda val=r: self.set_age_rating(val))
            btn.pack(side="left", padx=3); setattr(self, f"age_btn_{r}", btn)

        self.entry_tags_manual = self.create_styled_entry("Хештеги", 8)
        self.text_description = ctk.CTkTextbox(self.main_container, font=self.main_font, height=200, border_width=1, border_color=self.palette["border"], fg_color=self.palette["input_bg"])
        self.text_description.grid(row=9, column=0, pady=15, sticky="ew")
        self.text_description.insert("0.0", self.placeholder_text); self.text_description.configure(text_color=self.palette["placeholder"])
        self.text_description.bind("<FocusIn>", self.remove_placeholder); self.text_description.bind("<FocusOut>", self.add_placeholder)
        self.desc_counter = ctk.CTkLabel(self.main_container, text="", font=("Segoe UI", 11), text_color=self.palette["text_secondary"])
        self.desc_counter.grid(row=10, column=0, sticky="e", pady=(0, 2))
        self.text_description.bind("<KeyRelease>", lambda e: self._update_desc_counter())

        tags_box = ctk.CTkFrame(self.main_container, fg_color="transparent"); tags_box.grid(row=11, column=0, pady=10, sticky="ew")
        for tag in self.settings.get("hashtags", []):
            btn = ctk.CTkButton(tags_box, text=tag, font=("Segoe UI", 13), height=32, corner_radius=8,
                                fg_color="transparent", border_width=1, border_color=self.accent_blue,
                                text_color=self.accent_blue, command=lambda t=tag: self.toggle_chip_tag(t))
            self.current_tag_widgets.append(btn); setattr(self, f"tag_btn_{tag}", btn)

        file_container = ctk.CTkFrame(self.main_container, height=80, fg_color=self.palette["card"], corner_radius=10, border_width=1)
        file_container.grid(row=12, column=0, pady=20, sticky="ew"); file_container.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(file_container, text="Выбрать файлы", font=self.main_font, width=180, height=45, command=self.select_files_dialog, fg_color=self.accent_blue, hover_color=self.palette["accent_hover"]).grid(row=0, column=0, padx=15, pady=15)
        ctk.CTkLabel(file_container, text="Или перетащите их сюда", font=(self.main_font[0], 14), text_color=self.palette["text_secondary"]).grid(row=0, column=1, padx=20)

        self.files_list_container = ctk.CTkFrame(self.main_container, fg_color="transparent"); self.files_list_container.grid(row=13, column=0, pady=(0, 20), sticky="ew")
        self.update_file_list_display()

        social_box = ctk.CTkFrame(self.main_container, fg_color=self.palette["card"], corner_radius=10, border_width=1)
        social_box.grid(row=14, column=0, pady=10, sticky="ew"); social_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(social_box, text="Где публиковать новость:", font=(self.main_font[0], 15, "bold")).grid(row=0, column=0, padx=20, pady=(15, 10), sticky="w")
        self.social_vars = {}
        for i, (net_id, net_name) in enumerate([("Сайт", "Сайт (Госвеб)"), ("ВК", "Вконтакте"), ("ОК", "Одноклассники"), ("Max", "Max"), ("Telegram", "Telegram")]):
            # Telegram и Сайт (Госвеб) по умолчанию НЕ отмечены: публикация
            # туда обычно идёт вручную, а не автоматически (по просьбе заказчика)
            var = ctk.BooleanVar(value=(net_id not in ("Telegram", "Сайт"))); self.social_vars[net_id] = var
            row_f = ctk.CTkFrame(social_box, fg_color="transparent")
            p_bottom = 15 if i == 4 else 3
            row_f.grid(row=i+1, column=0, padx=40, pady=(3, p_bottom), sticky="ew")
            ctk.CTkCheckBox(row_f, text=net_name, variable=var, font=self.main_font, width=180).pack(side="left")
            ctk.CTkButton(row_f, text="Перейти ↗", width=80, height=24, font=("Segoe UI", 11), fg_color=self.palette["card_hover"], hover_color=self.palette["hover_soft"], text_color=self.palette["text"], command=lambda url=self.social_links[net_id]: webbrowser.open(url)).pack(side="left", padx=10)

        self.progress_bar = ctk.CTkProgressBar(self.main_container, width=400)
        self.progress_label = ctk.CTkLabel(self.main_container, text="", font=self.main_font)
        # Кнопки: Предпросмотр, Отправить, Сохранить черновик
        btn_action_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        btn_action_frame.grid(row=17, column=0, pady=50)

        self.btn_preview = ctk.CTkButton(btn_action_frame, text="👁 Предпросмотр", width=160, height=55, font=(self.main_font[0], 15), fg_color="transparent", border_width=1, border_color=self.palette["border"], hover_color=self.palette["hover_soft"], text_color=self.palette["text"], command=self.preview_report)
        self.btn_preview.pack(side="left", padx=10)

        self.btn_submit = ctk.CTkButton(btn_action_frame, text="Отправить", width=250, height=55, font=(self.main_font[0], 18, "bold"), fg_color=self.accent_blue, hover_color=self.palette["accent_hover"], command=self.submit_news)
        self.btn_submit.pack(side="left", padx=10)

        self.btn_save_draft = ctk.CTkButton(btn_action_frame, text="В черновики", width=200, height=55, font=(self.main_font[0], 16), fg_color="transparent", border_width=1, border_color=self.palette["border"], hover_color=self.palette["hover_soft"], text_color=self.palette["text"], command=self.save_as_draft)
        self.btn_save_draft.pack(side="left", padx=10)

        self._update_title_counter()
        self._update_desc_counter()
        self.after(200, self.rearrange_active_tags)

    def _update_title_counter(self):
        """Счётчик символов заголовка; краснеет при превышении лимита."""
        self._clear_required_highlight(self.entry_title)
        n = len(self.entry_title.get())
        text = f"{n}/{core.MAX_TITLE_LEN}"
        over = n > core.MAX_TITLE_LEN
        self.title_counter.configure(text=text, text_color=self.palette["error"] if over else self.palette["text_secondary"])

    def _update_desc_counter(self):
        """Счётчик символов описания (плейсхолдер не считается)."""
        self._clear_required_highlight(self.text_description)
        value = self.text_description.get("0.0", "end-1c")
        if value.strip() == self.placeholder_text:
            value = ""
        n = len(value)
        text = f"{n}/{core.MAX_DESC_LEN}"
        over = n > core.MAX_DESC_LEN
        self.desc_counter.configure(text=text, text_color=self.palette["error"] if over else self.palette["text_secondary"])

    # --- Подтверждение почты автора (в форме, один раз до смены почты) -------

    def _email_confirmed(self, email: str) -> bool:
        return core.is_same_email(self.settings.get("verified_email"), email)

    def _email_state(self) -> str:
        """Текущее состояние строки подтверждения: empty / verified /
        unverified / sending / code."""
        email = self.entry_email.get().strip()
        if self._email_sending:
            return "sending"
        if not email:
            return "empty"
        if self._vcode and core.is_same_email(self._vcode_email, email):
            return "code"
        if self._email_confirmed(email):
            return "verified"
        return "unverified"

    def _on_email_changed(self):
        self._clear_required_highlight(self.entry_email)
        # почта изменилась — ожидающий код относится уже не к ней
        email = self.entry_email.get().strip()
        if self._vcode and not core.is_same_email(self._vcode_email, email):
            self._vcode = None
            self._email_msg = None
        if self._email_state() != self._email_ui_state:
            self._render_email_status()

    def _render_email_status(self):
        """Перерисовывает строку статуса под полем «Ваш Email».

        Подтверждённая почта — зелёная отметка; новая — кнопка «Подтвердить
        почту»; после отправки кода — поле ввода и проверка, всё здесь же.
        Ошибки — красной строкой в этой же строке, без модальных окон.
        """
        f = self.email_status_frame
        for w in f.winfo_children():
            w.destroy()
        if getattr(self, "_resend_after_id", None):
            try:
                self.after_cancel(self._resend_after_id)
            except Exception:
                pass
            self._resend_after_id = None
        state = self._email_state()
        self._email_ui_state = state

        if state == "empty":
            if not self.settings.get("verified_email"):
                ctk.CTkLabel(f, text="На эту почту администратор отправит ответ по новости",
                             font=("Segoe UI", 11), text_color=self.palette["text_secondary"]).pack(anchor="w")
            return
        if state == "verified":
            ctk.CTkLabel(f, text="✓ Почта подтверждена — на неё придёт ответ администратора",
                         font=("Segoe UI", 12), text_color=self.palette["success"]).pack(anchor="w")
            return
        if state == "sending":
            ctk.CTkButton(f, text="Отправляю код...", height=30, width=170, state="disabled").pack(anchor="w")
            return
        if state == "unverified":
            row = ctk.CTkFrame(f, fg_color="transparent")
            row.pack(anchor="w", fill="x")
            ctk.CTkButton(row, text="Подтвердить почту", width=170, height=30, font=("Segoe UI", 12),
                          command=self.send_author_code).pack(side="left")
            ctk.CTkLabel(row, text="на почту придёт код из 6 цифр",
                         font=("Segoe UI", 11), text_color=self.palette["text_secondary"]).pack(side="left", padx=10)
            if self._email_msg:
                ctk.CTkLabel(f, text=self._email_msg, font=("Segoe UI", 11),
                             text_color=self.palette["error"]).pack(anchor="w", pady=(2, 0))
            return

        # state == "code": код отправлен, ждём ввод
        ctk.CTkLabel(f, text=f"Код отправлен на {self._vcode_email} (действует "
                             f"{core.VERIFICATION_CODE_TTL_SEC // 60} мин)",
                     font=("Segoe UI", 11), text_color=self.palette["text_secondary"]).pack(anchor="w")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(anchor="w", fill="x")
        self.entry_vcode = ctk.CTkEntry(row, width=130, height=34, justify="center",
                                        font=("Segoe UI", 15, "bold"), fg_color=self.palette["input_bg"],
                                        border_width=1, border_color=self.palette["border"])
        self.entry_vcode.pack(side="left", pady=(4, 0))
        self.entry_vcode.focus_set()
        self.entry_vcode.bind("<Return>", lambda _e: self._check_author_code())
        ctk.CTkButton(row, text="Проверить код", height=34, font=("Segoe UI", 12),
                      command=self._check_author_code).pack(side="left", padx=8, pady=(4, 0))
        if self._email_msg:
            ctk.CTkLabel(f, text=self._email_msg, font=("Segoe UI", 11),
                         text_color=self.palette["error"]).pack(anchor="w")
        self.btn_vresend = ctk.CTkButton(f, text="Отправить код ещё раз", height=26, width=220,
                                         font=("Segoe UI", 11), fg_color="transparent", border_width=1,
                                         border_color=self.palette["border"],
                                         text_color=self.palette["text_secondary"],
                                         hover_color=self.palette["hover_soft"],
                                         command=self.send_author_code)
        self.btn_vresend.pack(anchor="w", pady=(4, 0))
        left = int(self._vcode_sent_at + core.VERIFICATION_CODE_RESEND_SEC - time.monotonic())
        if left > 0:
            self.btn_vresend.configure(state="disabled", text=f"Отправить код ещё раз (через {left} с)")
            self._resend_after_id = self.after(1000, self._tick_resend)

    def send_author_code(self):
        """Отправляет код подтверждения на почту автора (в фоне)."""
        email = self.entry_email.get().strip()
        if not core.is_valid_email(email):
            self.entry_email.configure(border_color=self.palette["error"])
            self._email_msg = "Укажите корректную почту."
            self._render_email_status()
            self.entry_email.focus_set()
            return
        self._email_sending = True
        self._email_msg = None
        self._render_email_status()
        smtp = self.settings

        def worker():
            try:
                code = core.generate_verification_code()
                msg = MIMEMultipart()
                msg['From'] = smtp["smtp_user"]
                msg['To'] = email
                msg['Subject'] = core.VERIFICATION_EMAIL_SUBJECT
                msg.attach(MIMEText(core.build_verification_email_html(code), 'html'))
                with smtplib.SMTP_SSL(smtp["smtp_server"], int(smtp["smtp_port"]),
                                      timeout=core.SMTP_TIMEOUT_SEC) as server:
                    server.login(smtp["smtp_user"], smtp["smtp_password"])
                    server.send_message(msg)
                self.ui_post(lambda: self._author_code_sent(email, code))
            except Exception as e:
                log.exception("Не удалось отправить код подтверждения почты")
                auth_failed = core.is_auth_error(e)
                self.ui_post(lambda: self._author_code_failed(auth_failed))

        threading.Thread(target=worker, daemon=True).start()

    def _author_code_sent(self, email, code):
        self._vcode = code
        self._vcode_email = email
        self._vcode_expires = time.monotonic() + core.VERIFICATION_CODE_TTL_SEC
        self._vcode_attempts = 0
        self._vcode_sent_at = time.monotonic()
        self._email_sending = False
        self._email_msg = None
        self._render_email_status()

    def _author_code_failed(self, auth_failed):
        self._email_sending = False
        self._vcode = None
        if auth_failed:
            self._email_msg = ("Пароль программы не подошёл. Обновите его: "
                               "Настройки → режим администратора.")
        else:
            self._email_msg = "Не удалось отправить код — проверьте интернет и попробуйте ещё раз."
        self._render_email_status()

    def _tick_resend(self):
        """Обновляет кнопку повторной отправки кода (обратный отсчёт)."""
        if not getattr(self, "btn_vresend", None) or not self.btn_vresend.winfo_exists():
            return
        left = int(self._vcode_sent_at + core.VERIFICATION_CODE_RESEND_SEC - time.monotonic())
        if left > 0:
            self.btn_vresend.configure(text=f"Отправить код ещё раз (через {left} с)")
            self._resend_after_id = self.after(1000, self._tick_resend)
        else:
            self.btn_vresend.configure(state="normal", text="Отправить код ещё раз")

    def _check_author_code(self):
        entered = (self.entry_vcode.get() or "").strip()
        if not self._vcode or time.monotonic() > self._vcode_expires:
            self._vcode = None
            self._email_msg = "Код истёк — запросите новый."
            self._render_email_status()
            return
        if entered == self._vcode:
            # почта подтверждена: запоминаем до смены почты
            self.settings["verified_email"] = self._vcode_email
            self.save_settings()
            self._vcode = None
            self._email_msg = None
            self._render_email_status()
            return
        self._vcode_attempts += 1
        left = core.VERIFICATION_CODE_MAX_ATTEMPTS - self._vcode_attempts
        if left <= 0:
            self._vcode = None
            self._email_msg = "Слишком много неверных попыток — запросите новый код."
        else:
            self._email_msg = f"Неверный код. Осталось попыток: {left}"
        self._render_email_status()

    def create_styled_entry(self, placeholder, row):
        e = ctk.CTkEntry(self.main_container, placeholder_text=placeholder, height=50, font=self.main_font, border_width=1)
        e.grid(row=row, column=0, pady=8, sticky="ew"); return e

    def set_age_rating(self, value):
        self.age_rating = value
        for r in ["0+", "6+", "12+", "16+", "18+"]:
            btn = getattr(self, f"age_btn_{r}")
            is_s = (r == value)
            btn.configure(
                fg_color=self.accent_blue if is_s else "transparent",
                text_color=self.palette["on_accent"] if is_s else self.palette["text_secondary"],
                border_color=self.accent_blue if is_s else self.palette["border"],
            )

    def toggle_chip_tag(self, tag):
        btn = getattr(self, f"tag_btn_{tag}")
        is_active = (btn.cget("fg_color") == "transparent")
        btn.configure(fg_color=self.accent_blue if is_active else "transparent", text_color=self.palette["on_accent"] if is_active else self.accent_blue)
        # B3: обновляем поле хештегов токен-по-токену, не затирая ручной ввод
        new_text = core.merge_tag_tokens(self.entry_tags_manual.get(), tag, is_active)
        self.entry_tags_manual.delete(0, 'end')
        self.entry_tags_manual.insert(0, new_text)

    def remove_placeholder(self, event):
        if self.text_description.get("0.0", "end-1c").strip() == self.placeholder_text:
            self.text_description.delete("0.0", "end"); self.text_description.configure(text_color=self.palette["text"])
        self._update_desc_counter()

    def add_placeholder(self, event):
        if not self.text_description.get("0.0", "end-1c").strip():
            self.text_description.insert("0.0", self.placeholder_text); self.text_description.configure(text_color=self.palette["placeholder"])
        self._update_desc_counter()

    def select_files_dialog(self):
        files = filedialog.askopenfilenames(title="Выберите файлы")
        if files: self.add_files(files)

    def handle_windnd_drop(self, files):
        decoded = []
        for f in files:
            try:
                # В Windows windnd возвращает пути в виде байтов в локальной кодировке
                if isinstance(f, bytes):
                    path = f.decode('mbcs')
                else:
                    path = f
                if os.path.exists(path):
                    decoded.append(os.path.abspath(path))
            except Exception:
                log.warning("Не удалось обработать перетащенный файл: %r", f, exc_info=True)
        if decoded: self.after(100, lambda: self.add_files(decoded))

    def add_files(self, new_files):
        err = False
        for f in new_files:
            if len(self.selected_files) < core.MAX_FILES:
                if f not in self.selected_files: self.selected_files.append(f)
            else: err = True
        self.update_file_list_display(error=err)

    def remove_file(self, path):
        if path in self.selected_files: self.selected_files.remove(path); self.update_file_list_display()

    def _missing_required(self, email: str, title: str, desc: str) -> list[str]:
        """Незаполненные обязательные поля (для подсветки и текста ошибки)."""
        missing = []
        if not core.is_valid_email(email or ""):
            missing.append("Ваш Email")
        if not (title or "").strip():
            missing.append("Название новости")
        if not (desc or "").strip() or desc == self.placeholder_text:
            missing.append("Описание")
        return missing

    def _highlight_missing(self, missing: list[str]) -> None:
        """Красная рамка на незаполненных обязательных полях + фокус на первом.

        Подсветка снимается автоматически, как только в поле начинают
        печатать (см. _clear_required_highlight).
        """
        email_bad = "Ваш Email" in missing
        title_bad = "Название новости" in missing
        desc_bad = "Описание" in missing
        self.entry_email.configure(border_color=self.palette["error"] if email_bad else self.palette["border"])
        self.entry_title.configure(border_color=self.palette["error"] if title_bad else self.palette["border"])
        self.text_description.configure(border_color=self.palette["error"] if desc_bad else self.palette["border"])
        target = (self.entry_email if email_bad else
                  self.entry_title if title_bad else
                  self.text_description if desc_bad else None)
        if target is not None:
            try:
                target.focus_set()
            except Exception:
                log.debug("Не удалось поставить фокус на обязательное поле", exc_info=True)

    def _clear_required_highlight(self, widget) -> None:
        """Снимает красную подсветку поля при вводе текста в него."""
        try:
            if str(widget.cget("border_color")) == self.palette["error"]:
                widget.configure(border_color=self.palette["border"])
        except Exception:
            pass

    def update_file_list_display(self, error=False):
        for w in self.files_list_container.winfo_children(): w.destroy()
        if not self.selected_files and not error:
            # без файлов список убираем из grid совсем: пустой CTkFrame
            # держит дефолтную высоту 200px и растягивал пустоту между
            # блоком файлов и соцсетями
            self.files_list_container.grid_forget()
            return
        self.files_list_container.grid(row=13, column=0, pady=(0, 20), sticky="ew")
        t = f"Выбрано файлов ({len(self.selected_files)}/{core.MAX_FILES}):"
        if error: t += " ⚠️ ЛИМИТ 10 ФАЙЛОВ!"
        color = self.palette["error"] if error else self.palette["text"]
        if self.selected_files:
            size_mb = core.total_files_size_mb(self.selected_files)
            t += f"  ·  {core.human_file_size(int(size_mb * 1024 * 1024))}"
            if size_mb > core.ATTACH_LIMIT_MB:
                t += "  ⚠️ ПРЕВЫШЕН ЛИМИТ ВЕСА!"
                color = self.palette["error"]
            elif size_mb > core.ATTACH_WARN_MB:
                t += "  (внимание: большой объём, отправка может занять время)"
                color = self.palette["error"]
        ctk.CTkLabel(self.files_list_container, text=t, font=(self.main_font[0], 13, "bold"), text_color=color).pack(anchor="w", pady=(10, 5))
        if not self.selected_files: return
        cards = ctk.CTkFrame(self.files_list_container, fg_color="transparent"); cards.pack(fill="x")
        for i, f in enumerate(self.selected_files):
            card = ctk.CTkFrame(cards, corner_radius=8, border_width=1, fg_color=self.palette["chip"], border_color=self.palette["border"])
            card.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="ew"); cards.columnconfigure(i % 2, weight=1)

            # Миниатюра (изображения) или значок файла
            thumb_box = ctk.CTkFrame(card, width=84, height=84, corner_radius=6, fg_color=self.palette["thumb_bg"])
            thumb_box.pack(side="left", padx=8, pady=8); thumb_box.pack_propagate(False)
            img = self._get_thumbnail(f)
            if img:
                ctk.CTkLabel(thumb_box, text="", image=img).pack(expand=True)
            else:
                ctk.CTkLabel(thumb_box, text="📄", font=("Segoe UI Emoji", 30)).pack(expand=True)

            # Имя и размер файла
            info = ctk.CTkFrame(card, fg_color="transparent")
            info.pack(side="left", fill="both", expand=True, pady=8, padx=(0, 4))
            ctk.CTkLabel(info, text=os.path.basename(f), font=("Segoe UI", 12), anchor="w", justify="left", wraplength=170).pack(anchor="w")
            try: size_text = core.human_file_size(os.path.getsize(f))
            except OSError: size_text = ""
            if size_text:
                ctk.CTkLabel(info, text=size_text, font=("Segoe UI", 11), text_color=self.palette["text_secondary"], anchor="w").pack(anchor="w")

            ctk.CTkButton(card, text="✕", width=28, height=28, corner_radius=6, fg_color="transparent", text_color=self.palette["error"], hover_color=self.palette["card_hover"], command=lambda p=f: self.remove_file(p)).pack(side="right", padx=6, pady=8)

    def _get_thumbnail(self, path):
        """Миниатюра изображения (CTkImage) с кэшем; False — файл не изображение.

        Кэш keyed by путь+mtime+размер: замена файла с тем же именем
        перестраивает миниатюру, повторные отображения не перечитывают файл.
        """
        if not THUMBNAILS_AVAILABLE or not core.is_image_file(path):
            return False
        key = core.thumbnail_cache_key(path)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        thumb = False
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)  # учёт ориентации съёмки (EXIF)
                im.thumbnail((96, 96))
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                thumb = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
        except Exception:
            log.warning("Не удалось создать миниатюру: %s", path, exc_info=True)
        self._thumb_cache[key] = thumb
        return thumb

    def submit_news(self):
        if self._sending:
            return  # отправка уже идёт
        email, branch, title = self.entry_email.get().strip(), self.branch_opt.get(), self.entry_title.get().strip()
        desc = self.text_description.get("0.0", "end-1c").strip()
        missing = self._missing_required(email, title, desc)
        if missing:
            self._highlight_missing(missing)
            CustomMessagebox(self, "Ошибка",
                             "Заполните обязательные поля:\n• " + "\n• ".join(missing), is_error=True)
            return
        # Почта автора должна быть подтверждена кодом: администратор
        # отвечает именно на неё — «левые» адреса не пропускаем
        if not self._email_confirmed(email):
            self.entry_email.configure(border_color=self.palette["error"])
            if self._vcode:
                self._email_msg = "Введите код из письма — он уже отправлен на вашу почту."
            else:
                self._email_msg = "Подтвердите почту — код придёт на неё за минуту."
            self._render_email_status()
            target = (self.entry_vcode
                      if getattr(self, "entry_vcode", None) and self.entry_vcode.winfo_exists()
                      else self.entry_email)
            try:
                target.focus_set()
            except Exception:
                pass
            return
        error = core.validate_submission(email, title, desc, self.placeholder_text, files=self.selected_files)
        if error:
            CustomMessagebox(self, "Ошибка", error, is_error=True); return

        if not self.selected_files:
            dialog = CustomYesNoBox(self, "Внимание", "Вы не прикрепили файлы к этой новости. Отправить без файлов?", yes_text="Отправить без файлов", no_text="Прикрепить файлы")
            if not dialog.get_result():
                return

        self.settings["last_branch"] = branch
        # verified_email не трогаем: он меняется только проверкой кода
        self.save_settings()
        self._set_sending(True)
        self.progress_bar.grid(row=15, column=0, pady=10); self.progress_bar.set(0)
        self.progress_label.grid(row=16, column=0); self.progress_label.configure(text="Начинаем отправку...")
        # Снимок данных формы: фоновый поток работает только с этими значениями,
        # а не с живыми виджетами (Tkinter нельзя трогать из другого потока)
        payload = self._collect_payload()
        threading.Thread(target=self.process_sending, args=(payload,), daemon=True).start()

    def _collect_payload(self):
        """Снимок данных формы (для отправки и предпросмотра)."""
        return {
            "email": self.entry_email.get().strip(),
            "branch": self.branch_opt.get(),
            "title": self.entry_title.get().strip(),
            "desc": self.text_description.get("0.0", "end-1c").strip(),
            "tags": self.entry_tags_manual.get().strip(),
            "files": list(self.selected_files),
            "socials": [net for net, var in self.social_vars.items() if var.get()],
            "age_rating": self.age_rating,
            "folder": core.make_cloud_folder(),
        }

    def preview_report(self):
        """Показывает письмо, которое получит администратор, в браузере.

        HTML собирается той же функцией, что и реальная отправка —
        предпросмотр буквальный, без расхождений.
        """
        payload = self._collect_payload()
        missing = self._missing_required(payload["email"], payload["title"], payload["desc"])
        if missing:
            self._highlight_missing(missing)
            CustomMessagebox(self, "Ошибка",
                             "Заполните обязательные поля:\n• " + "\n• ".join(missing), is_error=True)
            return
        error = core.validate_submission(payload["email"], payload["title"], payload["desc"],
                                         self.placeholder_text, files=payload["files"])
        if error:
            CustomMessagebox(self, "Ошибка", error, is_error=True); return
        try:
            folder = payload["folder"]
            file_links = [(core.public_file_url(self.settings["webdav_url"], folder, name), name)
                          for name in core.unique_remote_names(payload["files"])]
            html_body = core.build_report_html(
                title=payload["title"],
                age_rating=payload["age_rating"],
                desc=payload["desc"],
                branch=payload["branch"],
                tags=payload["tags"],
                folder_link=core.cloud_folder_link(folder),
                file_links=file_links,
                social_links=self.social_links,
                active_socials=payload["socials"],
                author_email=payload["email"],
            )
            import tempfile
            fd, path = tempfile.mkstemp(suffix=".html", prefix="nad_preview_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(html_body)
            webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
            log.info("Открыт предпросмотр письма: %s", path)
        except Exception as e:
            log.exception("Не удалось построить предпросмотр")
            CustomMessagebox(self, "Ошибка", f"Не удалось открыть предпросмотр: {e}", is_error=True)

    def _set_sending(self, on):
        """Блокирует навигацию и кнопки форм на время фоновой отправки (B5)."""
        self._sending = on
        state = "disabled" if on else "normal"
        for btn in (self.btn_send, self.btn_drafts, self.btn_history, self.btn_settings):
            btn.configure(state=state)
        self.btn_submit.configure(state=state, text="Отправка..." if on else "Отправить")
        self.btn_save_draft.configure(state=state)

    def _finish_sending(self):
        """Восстанавливает UI после фоновой отправки (выполняется в потоке UI)."""
        self.progress_bar.grid_forget()
        self.progress_label.grid_forget()
        self._set_sending(False)

    def process_sending(self, payload):
        """Фоновая загрузка файлов в облако и отправка письма администратору.

        Все обращения к UI — только через self.after (B5: обращение к виджетам
        Tkinter из фонового потока приводило к TclError и падению отправки).
        Сетевые операции выполняются с повторами (обрыв связи не «теряет» новость).
        """
        def ui(fn):
            # Только через очередь: обращения к Tkinter из фонового потока
            # напрямую (в т.ч. self.after) могут обрушить приложение
            try:
                self._ui_queue.put(fn)
            except Exception:
                log.debug("Окно закрыто во время отправки: обновление UI пропущено")

        try:
            folder = payload["folder"]
            files = payload["files"]
            options = {
                'webdav_hostname': self.settings["webdav_url"],
                'webdav_login': self.settings["webdav_login"],
                'webdav_password': self.settings["webdav_password"],
            }
            client = Client(options)
            try:
                core.with_retries(lambda: client.mkdir(folder), what="создание папки")
            except Exception:
                log.debug("Не удалось создать папку %s (возможно, уже существует)", folder, exc_info=True)

            file_links = []
            for i, (path, remote_name) in enumerate(zip(files, core.unique_remote_names(files))):
                ui(lambda i=i: self.progress_label.configure(text=f"Загрузка {i + 1}/{len(files)}..."))
                core.with_retries(
                    lambda p=path, rn=remote_name: client.upload_sync(remote_path=f"{folder}/{rn}", local_path=p),
                    what=f"загрузка {remote_name}",
                )
                file_links.append((core.public_file_url(self.settings["webdav_url"], folder, remote_name), remote_name))
                ui(lambda i=i: self.progress_bar.set((i + 1) / max(1, len(files)) * 0.7))

            ui(lambda: self.progress_label.configure(text="Отправка письма..."))

            html_body = core.build_report_html(
                title=payload["title"],
                age_rating=payload["age_rating"],
                desc=payload["desc"],
                branch=payload["branch"],
                tags=payload["tags"],
                folder_link=core.cloud_folder_link(folder),
                file_links=file_links,
                social_links=self.social_links,
                active_socials=payload["socials"],
                author_email=payload["email"],
            )
            msg = MIMEMultipart()
            msg['From'] = self.settings["smtp_user"]
            msg['To'] = self.settings["admin_email"]
            # Ответ администратора уходит напрямую автору новости
            # (адрес подтверждён кодом — см. _check_author_code)
            msg['Reply-To'] = payload['email']
            msg['Subject'] = core.news_subject(payload['title'], payload['branch'])
            msg.attach(MIMEText(html_body, 'html'))

            def send_mail():
                with smtplib.SMTP_SSL(self.settings["smtp_server"], self.settings["smtp_port"], timeout=core.SMTP_TIMEOUT_SEC) as s:
                    s.login(self.settings["smtp_user"], self.settings["smtp_password"])
                    s.send_message(msg)

            core.with_retries(send_mail, what="отправка письма")

            ui(lambda: self.progress_bar.set(1.0))
            ui(lambda: self.progress_label.configure(text="Готово!"))

            # История отправок с ограничением размера (B14): полная карточка —
            # по ней работают «Просмотр» и «Повторить»
            hist_entry = {
                "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
                "title": payload["title"],
                "branch": payload["branch"],
                "desc": payload["desc"],
                "tags": payload["tags"],
                "age_rating": payload["age_rating"],
                "socials": payload["socials"],
                "files": [os.path.basename(p) for p in payload["files"]],
                "file_links": [link for link, _ in file_links],
                "local_files": list(payload["files"]),  # для «Повторить», если файлы ещё на месте
                "folder": folder,
            }
            self.settings.setdefault("history", []).insert(0, hist_entry)
            del self.settings["history"][core.HISTORY_LIMIT:]
            self.save_settings()

            self.selected_files = []
            admin = self.settings.get("admin_email") or "почту администратора"
            ui(lambda: CustomMessagebox(
                self, "Отправлено",
                f"Новость отправлена!\n\n"
                f"Администратор получит письмо на {admin}.\n\n"
                f"Новость сохранена в разделе «История»."))
            ui(lambda: self.after(500, self.show_send_frame))
        except Exception as e:
            err = str(e)
            log.exception("Ошибка отправки новости")
            self._last_failed_payload = payload
            auth_failed = core.is_auth_error(e)

            def show_failure():
                if auth_failed:
                    # пароль не подошёл (например, его сменили):
                    # новость в любом случае сохраняем, предлагаем
                    # сразу ввести актуальный пароль
                    dialog = CustomYesNoBox(
                        self, "Пароль не подходит",
                        "Новость не отправлена: пароль облачного аккаунта не подошёл "
                        "(возможно, его сменили).\n\n"
                        "Новость сохранена в черновики. Открыть настройки,\n"
                        "чтобы ввести актуальный пароль?",
                        yes_text="Открыть настройки", no_text="Позже")
                    self._save_draft_from_payload(self._last_failed_payload)
                    self._last_failed_payload = None
                    if dialog.get_result():
                        self.show_settings_frame()
                    return
                dialog = CustomYesNoBox(
                    self, "Не отправлено",
                    f"Новость не удалось отправить:\n\n{err}\n\n"
                    f"Сохранить её в черновики, чтобы не потерять?",
                    yes_text="Сохранить в черновики", no_text="Не сохранять")
                if dialog.get_result():
                    self._save_draft_from_payload(self._last_failed_payload)
                    self._last_failed_payload = None

            ui(show_failure)
        finally:
            ui(self._finish_sending)

    def _save_draft_from_payload(self, payload):
        """Сохраняет несостоявшуюся/текущую новость в черновики (молча)."""
        if not payload:
            return
        draft = {
            "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            "title": payload.get("title") or "Без названия",
            "branch": payload.get("branch", core.BRANCH_NOT_SPECIFIED),
            "age_rating": payload.get("age_rating", "0+"),
            "desc": payload.get("desc", ""),
            "tags_manual": payload.get("tags", ""),
            "tags": [t for t in (payload.get("tags") or "").split() if t],
            "socials": payload.get("socials", []),
            "files": list(payload.get("files", [])),
        }
        self.settings.setdefault("drafts", []).insert(0, draft)
        self.save_settings()
        log.info("Новость сохранена в черновики (автосохранение)")

    def save_as_draft(self):
        if self._sending:
            return
        try:
            title = self.entry_title.get().strip()
            if not title:
                CustomMessagebox(self, "Ошибка", "Укажите хотя бы название новости для сохранения черновика!", is_error=True)
                return

            draft = {
                "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
                "title": title,
                "branch": self.branch_opt.get(),
                "age_rating": self.age_rating,
                "desc": self.text_description.get("0.0", "end-1c").strip(),
                "tags": [t for t in self.settings.get("hashtags", []) if hasattr(self, f"tag_btn_{t}") and getattr(self, f"tag_btn_{t}").cget("fg_color") != "transparent"],
                "tags_manual": self.entry_tags_manual.get().strip(),
                "socials": [net for net, var in self.social_vars.items() if var.get()],
                # B2: список прикреплённых файлов сохраняется в черновик
                # (раньше черновик всегда терял файлы)
                "files": list(self.selected_files),
            }

            if "drafts" not in self.settings or not isinstance(self.settings["drafts"], list):
                self.settings["drafts"] = []
                
            self.settings["drafts"].insert(0, draft)
            self.save_settings()
            
            CustomMessagebox(self, "Сохранено", "Новость успешно сохранена в черновики.")
            
            # Очищаем форму
            self.entry_title.delete(0, 'end')
            self.text_description.delete("0.0", "end")
            self.add_placeholder(None)
            self.selected_files = []
            self.update_file_list_display()
        except Exception as e:
            log.exception("Не удалось сохранить черновик")
            CustomMessagebox(self, "Ошибка сохранения", f"Не удалось сохранить черновик: {e}", is_error=True)

    def show_drafts_frame(self):
        self.clear_main_container()
        self._apply_palette()
        ctk.CTkLabel(self.main_container, text="Черновики", font=self.header_font, text_color=self.palette["text"]).grid(row=0, column=0, pady=(0, 40), sticky="w")

        drafts = self.settings.get("drafts", [])
        if not drafts:
            ctk.CTkLabel(self.main_container, text="У вас пока нет сохраненных черновиков.", font=self.main_font, text_color=self.palette["text_secondary"]).grid(row=1, column=0, sticky="w")
            return

        for i, item in enumerate(drafts):
            card = ctk.CTkFrame(self.main_container, fg_color=self.palette["card"], corner_radius=10, border_width=1, border_color=self.palette["border"])
            card.grid(row=i+1, column=0, pady=10, sticky="ew")
            card.columnconfigure(0, weight=1)

            title = item.get("title", "Без названия")
            date = item.get("date", "Неизвестно")
            files_count = len(item.get("files", []))

            ctk.CTkLabel(card, text=title, font=(self.main_font[0], 18, "bold"), text_color=self.palette["text"]).grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")
            ctk.CTkLabel(card, text=f"Сохранено: {date} | Прикреплено файлов: {files_count}", font=(self.main_font[0], 13), text_color=self.palette["text_secondary"]).grid(row=1, column=0, padx=20, pady=(0, 15), sticky="w")
            
            btn_box = ctk.CTkFrame(card, fg_color="transparent")
            btn_box.grid(row=0, column=1, rowspan=2, padx=20, pady=15, sticky="e")
            
            ctk.CTkButton(btn_box, text="✏️ Продолжить", width=120, height=35, fg_color=self.accent_blue, hover_color=self.palette["accent_hover"], command=lambda d=item: self.load_draft(d)).pack(side="left", padx=5)
            ctk.CTkButton(btn_box, text="🗑 Удалить", width=100, height=35, fg_color=self.palette["danger"], hover_color=self.palette["danger_hover"], command=lambda idx=i: self.delete_draft(idx)).pack(side="left", padx=5)

    def load_draft(self, draft):
        self.show_send_frame()
        self._fill_form_from_item(draft, warn_missing_files=True)

    def _fill_form_from_item(self, item, warn_missing_files=True):
        """Заполняет форму отправки из черновика/записи истории («Повторить»)."""
        branch = item.get("branch")
        # старые черновики/записи без филиала и снятые с списка значения
        # не должны попадать в выпадающий список мимо «Не указывать»
        self.branch_opt.set(branch if branch in self.branch_values else core.BRANCH_NOT_SPECIFIED)
        self.entry_title.delete(0, 'end')
        self.entry_title.insert(0, item.get("title", ""))

        self.set_age_rating(item.get("age_rating", "0+"))

        desc = item.get("desc", "")
        self.text_description.delete("0.0", "end")
        if desc and desc != self.placeholder_text:
            self.text_description.insert("0.0", desc)
            self.text_description.configure(text_color=self.palette["text"])
        else:
            self.add_placeholder(None)

        # Восстанавливаем хештеги: состояние чипов + ручной ввод (B3)
        saved_tags = item.get("tags", [])
        for tag in self.settings.get("hashtags", []):
            btn = getattr(self, f"tag_btn_{tag}", None)
            if btn:
                is_active = tag in saved_tags
                btn.configure(fg_color=self.accent_blue if is_active else "transparent", text_color=self.palette["on_accent"] if is_active else self.accent_blue)
        manual = item.get("tags_manual")
        if manual is None:
            # записи старого формата: показываем чипы
            manual = " ".join(saved_tags)
        self.entry_tags_manual.delete(0, 'end')
        self.entry_tags_manual.insert(0, manual)

        # Восстанавливаем соцсети
        saved_socials = item.get("socials", [])
        for net in self.social_vars:
            self.social_vars[net].set(net in saved_socials)

        # Восстанавливаем файлы с проверкой существования
        saved_files = item.get("files", [])
        self.selected_files = []
        missing_files = False
        for f in saved_files:
            if os.path.exists(f):
                self.selected_files.append(f)
            else:
                missing_files = True

        self.update_file_list_display()
        self._update_title_counter()
        self._update_desc_counter()

        if warn_missing_files and missing_files:
            CustomMessagebox(self, "Внимание", "Некоторые файлы были перемещены или удалены с компьютера, поэтому они не прикреплены.")

    def delete_draft(self, index):
        dialog = CustomYesNoBox(self, "Удаление", "Вы уверены, что хотите удалить этот черновик навсегда?")
        if dialog.get_result():
            del self.settings["drafts"][index]
            self.save_settings()
            self.show_drafts_frame()

    def show_history_frame(self):
        self.clear_main_container()
        self._apply_palette()
        ctk.CTkLabel(self.main_container, text="История отправленных новостей", font=self.header_font, text_color=self.palette["text"]).grid(row=0, column=0, pady=(0, 40), sticky="w")

        history = self.settings.get("history", [])
        if not history:
            ctk.CTkLabel(self.main_container, text="История пуста. Отправленные новости появятся здесь.", font=self.main_font, text_color=self.palette["text_secondary"]).grid(row=1, column=0, sticky="w")
            return

        for i, item in enumerate(history):
            card = ctk.CTkFrame(self.main_container, fg_color=self.palette["card"], corner_radius=10, border_width=1, border_color=self.palette["border"])
            card.grid(row=i+1, column=0, pady=10, sticky="ew")
            card.columnconfigure(0, weight=1)

            title = item.get("title", "Без названия")
            date = item.get("date", "Неизвестно")
            branch = item.get("branch", "Неизвестный филиал")
            files_count = len(item.get("files", []))

            ctk.CTkLabel(card, text=title, font=(self.main_font[0], 18, "bold"), text_color=self.palette["text"]).grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")
            ctk.CTkLabel(card, text=f"{date} | {branch} | Файлов: {files_count}", font=(self.main_font[0], 13), text_color=self.palette["text_secondary"]).grid(row=1, column=0, padx=20, pady=(0, 15), sticky="w")

            btn_box = ctk.CTkFrame(card, fg_color="transparent")
            btn_box.grid(row=0, column=1, rowspan=2, padx=20, pady=15, sticky="e")
            ctk.CTkButton(btn_box, text="👁 Просмотр", width=110, height=35, fg_color=self.palette["card_hover"], hover_color=self.palette["hover_soft"], text_color=self.palette["text"], command=lambda it=item: self.view_history_item(it)).pack(side="left", padx=5)
            ctk.CTkButton(btn_box, text="↻ Повторить", width=110, height=35, fg_color=self.accent_blue, hover_color=self.palette["accent_hover"], command=lambda it=item: self.repeat_from_history(it)).pack(side="left", padx=5)

    def view_history_item(self, item):
        """Полный просмотр отправленной новости из истории."""
        win = ctk.CTkToplevel(self)
        win.title("Новость из истории")
        win.geometry("700x640")
        win.attributes("-topmost", True)
        p = self.palette
        win.configure(fg_color=p["bg"])
        try:
            win.grab_set()
        except Exception:
            log.debug("grab_set в просмотре истории не сработал", exc_info=True)

        box = ctk.CTkScrollableFrame(win, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=20, pady=20)

        def add(text, font, color, pady=(0, 6), wrap=620):
            ctk.CTkLabel(box, text=text, font=font, text_color=color, justify="left", wraplength=wrap).pack(anchor="w", pady=pady)

        add(item.get("title", "Без названия"), ("Segoe UI", 22, "bold"), p["text"], pady=(0, 4))
        add(f"{item.get('date', '—')} | {item.get('branch', '—')} | {item.get('age_rating', '—')}",
            ("Segoe UI", 13), p["text_secondary"])
        add("Описание", ("Segoe UI", 14, "bold"), p["text"], pady=(14, 2))
        add(item.get("desc") or "—", ("Segoe UI", 14), p["text"])
        add("Хештеги", ("Segoe UI", 14, "bold"), p["text"], pady=(14, 2))
        tags = item.get("tags")
        tags_text = tags if isinstance(tags, str) else " ".join(tags or [])
        add(tags_text or "—", ("Segoe UI", 14), p["text"])

        socials = item.get("socials") or []
        add("Где публиковать", ("Segoe UI", 14, "bold"), p["text"], pady=(14, 2))
        add(", ".join(socials) if socials else "—", ("Segoe UI", 14), p["text"])

        files = item.get("files") or []
        add("Файлы", ("Segoe UI", 14, "bold"), p["text"], pady=(14, 2))
        if files:
            links = item.get("file_links") or []
            for i, name in enumerate(files):
                link = links[i] if i < len(links) else None
                if link:
                    ctk.CTkLabel(box, text=f"• {name}", font=("Segoe UI", 13), text_color=p["accent"], cursor="hand2").pack(anchor="w")
                    box.winfo_children()[-1].bind("<Button-1>", lambda e, u=link: webbrowser.open(u))
                else:
                    add(f"• {name}", ("Segoe UI", 13), p["text_secondary"], pady=(0, 2))
        else:
            add("—", ("Segoe UI", 14), p["text"])

        folder = item.get("folder")
        if folder:
            add("Папка в облаке", ("Segoe UI", 14, "bold"), p["text"], pady=(14, 2))
            lbl = ctk.CTkLabel(box, text=core.cloud_folder_link(folder), font=("Segoe UI", 13), text_color=p["accent"], cursor="hand2", wraplength=620, justify="left")
            lbl.pack(anchor="w")
            lbl.bind("<Button-1>", lambda e: webbrowser.open(core.cloud_folder_link(folder)))

        ctk.CTkButton(win, text="Закрыть", width=140, height=38, font=("Segoe UI", 14),
                      fg_color=p["card"], hover_color=p["card_hover"], border_width=1, text_color=p["text"], command=win.destroy).pack(pady=(0, 20))

    def repeat_from_history(self, item):
        """Заполняет форму отправки данными из истории («Повторить»)."""
        self.show_send_frame()
        tags = item.get("tags")
        # в истории теги — строка ручного ввода; форме нужен список для чипов
        tags_manual = tags if isinstance(tags, str) else " ".join(tags or [])
        tags_list = tags_manual.split() if tags_manual else []
        self._fill_form_from_item({
            **item,
            "files": item.get("local_files") or [],
            "tags": tags_list,
            "tags_manual": tags_manual,
        }, warn_missing_files=True)

    def show_settings_frame(self):
        self.clear_main_container()
        self._apply_palette()
        ctk.CTkLabel(self.main_container, text="Настройки", font=self.sub_header_font).grid(row=0, column=0, pady=(0, 25), sticky="w")

        # Внешний вид: тема оформления
        ctk.CTkLabel(self.main_container, text="Внешний вид:", font=(self.main_font[0], 15, "bold")).grid(row=1, column=0, pady=(0, 5), sticky="w")
        theme_f = ctk.CTkFrame(self.main_container, fg_color=self.palette["card"], corner_radius=10, border_width=1, border_color=self.palette["border"])
        theme_f.grid(row=2, column=0, pady=(0, 10), sticky="ew")
        ctk.CTkLabel(theme_f, text="Тема оформления:", font=self.main_font).pack(side="left", padx=20, pady=15)
        current_label = theme.APPEARANCE_BY_MODE.get(self.settings.get("appearance_mode", "dark"), "Тёмная")
        self.theme_segment = ctk.CTkSegmentedButton(theme_f, values=list(theme.APPEARANCE_LABELS),
                                                    command=self.change_theme, height=35, font=(self.main_font[0], 13))
        self.theme_segment.set(current_label)
        self.theme_segment.pack(side="right", padx=20, pady=15)

        # Версия и проверка обновлений
        ver_f = ctk.CTkFrame(self.main_container, fg_color="transparent")
        ver_f.grid(row=3, column=0, pady=(0, 5), sticky="ew")
        ctk.CTkLabel(ver_f, text=f"Версия: {core.APP_VERSION}", font=("Segoe UI", 12),
                     text_color=self.palette["text_secondary"]).pack(side="left")
        ctk.CTkButton(ver_f, text="Проверить обновления", width=170, height=28, font=("Segoe UI", 12),
                      fg_color=self.palette["card_hover"], hover_color=self.palette["hover_soft"], text_color=self.palette["text"],
                      command=self.check_for_updates_manual).pack(side="right")
        # ссылка нужна, чтобы блокировать кнопку на время проверки:
        # несколько нажатий подряд плодили стопку диалогов
        self.btn_check_updates = ver_f.winfo_children()[-1]

        # Аккаунт: единственный «профиль» — почта автора последней новости
        # (меняется прямо в форме отправки, отдельная кнопка не нужна)
        ctk.CTkLabel(self.main_container, text="Аккаунт:", font=(self.main_font[0], 15, "bold")).grid(row=4, column=0, pady=(30, 5), sticky="w")
        acc_f = ctk.CTkFrame(self.main_container, fg_color=self.palette["card"], corner_radius=10, border_width=1, border_color=self.palette["border"])
        acc_f.grid(row=5, column=0, pady=10, sticky="ew")
        ctk.CTkLabel(acc_f, text=f"Почта автора новостей: {self.settings.get('verified_email') or 'не подтверждена — укажите и подтвердите её в форме отправки'}", font=self.main_font).pack(side="left", padx=20, pady=15)

        self.admin_mode = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.main_container, text="Режим администратора (Тех. данные)", variable=self.admin_mode, command=self.toggle_admin_settings).grid(row=6, column=0, pady=(30, 10), sticky="w")

        self.tech_container = ctk.CTkFrame(self.main_container, corner_radius=10, border_width=1)
        self.create_tech_entry(self.tech_container, "WEBDAV_LOGIN:", "webdav_login", 0)
        self.create_tech_entry(self.tech_container, "WEBDAV_PASSWORD:", "webdav_password", 1, show="*")
        self.create_tech_entry(self.tech_container, "SENDER_EMAIL:", "smtp_user", 2)
        self.create_tech_entry(self.tech_container, "SENDER_PASSWORD:", "smtp_password", 3, show="*")
        self.create_tech_entry(self.tech_container, "RECEIVER_EMAIL:", "admin_email", 4)
        self.tech_container.grid(row=7, column=0, pady=10, sticky="ew")
        self.tech_container.columnconfigure(1, weight=1)
        if not self.admin_mode.get(): self.tech_container.grid_forget()

        ctk.CTkLabel(self.main_container, text="Список хештегов:", font=(self.main_font[0], 15, "bold")).grid(row=8, column=0, pady=(30, 15), sticky="w")
        self.hashtag_entry = ctk.CTkEntry(self.main_container, placeholder_text="Добавить #хештег", width=350, font=self.main_font, height=40)
        self.hashtag_entry.grid(row=9, column=0, sticky="w", padx=25)
        ctk.CTkButton(self.main_container, text="Добавить", width=120, height=40, command=self.add_new_hashtag).grid(row=9, column=0, sticky="w", padx=(390, 0))
        self.tags_container = ctk.CTkFrame(self.main_container, fg_color="transparent"); self.tags_container.grid(row=10, column=0, pady=15, sticky="w", padx=25)
        self.refresh_settings_tags()
        ctk.CTkButton(self.main_container, text="Сохранить настройки", height=45, width=250, font=(self.main_font[0], 16, "bold"), fg_color=self.accent_blue, command=self.save_all_settings).grid(row=11, column=0, pady=40, sticky="w")

    def check_for_updates_manual(self):
        """Кнопка «Проверить обновления» в настройках."""
        self.check_for_updates()

    def change_theme(self, label: str):
        """Переключение темы из настроек (Тёмная/Светлая/Системная)."""
        mode = theme.APPEARANCE_LABELS.get(label)
        if not mode:
            return
        if mode == self.settings.get("appearance_mode"):
            return
        self.settings["appearance_mode"] = mode
        self.save_settings()
        ctk.set_appearance_mode(mode)
        # Перерисовываем страницу: все виджеты читают палитру при создании,
        # статичный хром (окно/панель) перекрашивается в _apply_palette
        self.show_settings_frame()
        self.update_idletasks()

    def toggle_admin_settings(self):
        if self.admin_mode.get():
            self.tech_container.grid(row=7, column=0, pady=10, sticky="ew")
            self.tech_container.columnconfigure(1, weight=1)
        else: self.tech_container.grid_forget()

    def create_tech_entry(self, parent, label, key, row, show=None):
        ctk.CTkLabel(parent, text=label, font=self.main_font).grid(row=row, column=0, padx=20, pady=10, sticky="w")
        e = ctk.CTkEntry(parent, height=35, font=self.main_font, border_width=1, show=show)
        e.insert(0, self.settings.get(key, "")); e.grid(row=row, column=1, padx=20, pady=10, sticky="ew")
        setattr(self, f"entry_{key}", e)

    def refresh_settings_tags(self):
        for widget in self.tags_container.winfo_children(): widget.destroy()
        self.current_tag_widgets = []
        for tag in self.settings.get("hashtags", []):
            btn = ctk.CTkButton(self.tags_container, text=f"{tag} ✕", width=120, height=32, font=(self.main_font[0], 13), fg_color="transparent", border_width=1, border_color=self.palette["border"], text_color=self.palette["text"], hover_color=self.palette["card_hover"], command=lambda t=tag: self.remove_hashtag(t))
            self.current_tag_widgets.append(btn); self.rearrange_active_tags()

    def add_new_hashtag(self):
        tag = core.normalize_hashtag(self.hashtag_entry.get())
        if tag and tag not in self.settings["hashtags"]:
            self.settings["hashtags"].append(tag); self.hashtag_entry.delete(0, 'end'); self.refresh_settings_tags()

    def remove_hashtag(self, tag):
        self.settings["hashtags"].remove(tag); self.refresh_settings_tags()

    def save_all_settings(self):
        if hasattr(self, "entry_webdav_login"):
            for key in ["webdav_login", "webdav_password", "smtp_user", "smtp_password", "admin_email"]:
                value = getattr(self, f"entry_{key}").get().strip()
                self.settings[key] = value
                # пароль намеренно очищен — убираем и из Credential Manager
                if key in core.SECRET_KEYS and not value:
                    core.delete_secret(key)
        self.save_settings(); self.show_send_frame()

if __name__ == "__main__":
    # Лог в файл рядом с приложением (ротация 1 МБ × 3) + консоль
    file_handler = RotatingFileHandler(
        os.path.join(core.app_dir(), "app.log"),
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    # Любое необработанное исключение — в лог: в оконной сборке exe stderr
    # отсутствует, без этого Hook причины вылетов было бы не найти
    def _excepthook(exc_type, exc_val, exc_tb):
        log.critical("Необработанное исключение, приложение завершается",
                     exc_info=(exc_type, exc_val, exc_tb))

    sys.excepthook = _excepthook
    log.info("Запуск приложения (версия %s)", core.APP_VERSION)
    app = NewsApp()
    app.mainloop()
