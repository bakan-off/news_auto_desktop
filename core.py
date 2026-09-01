"""Чистая логика приложения, не зависящая от UI (Tkinter).

Выделена из main.py, чтобы её можно было покрывать автотестами (pytest)
без запуска GUI. Модуль не должен импортировать tkinter и customtkinter.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import os
import re
import secrets
import shutil
import smtplib
import sys
import time
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

log = logging.getLogger("news_core")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

APP_NAME = "КМЦБС Новости"
APP_VERSION = "1.4.0"
# Основной (публичный) репозиторий: исходники + релизы. Проверка
# обновлений читает веб-ленту тегов этого репозитория; отдельный
# репозиторий рассылок больше не используется.
GITHUB_REPO = "bakan-off/news_auto_desktop"

# --- Политика безопасности --------------------------------------------------

VERIFICATION_CODE_TTL_SEC = 600      # срок действия кода подтверждения e-mail
VERIFICATION_CODE_MAX_ATTEMPTS = 5   # попыток ввода кода подтверждения
SMTP_TIMEOUT_SEC = 30                # таймаут сетевых операций SMTP
HISTORY_LIMIT = 100                  # максимум записей в истории отправок

# --- Лимиты новости ---------------------------------------------------------

MAX_TITLE_LEN = 100                  # заголовок: разумный предел для письма
MAX_DESC_LEN = 5000                  # описание: защита от «залипшей» клавиши
ATTACH_WARN_MB = 50                  # предупреждение о суммарном весе вложений
ATTACH_LIMIT_MB = 200                # жёсткий предел суммарного веса вложений
MAX_FILES = 10                       # максимум прикреплённых файлов


# --- Файловые пути ---------------------------------------------------------


def app_dir() -> str:
    """Каталог приложения, не зависящий от текущей рабочей папки запуска.

    Для сборки PyInstaller (.exe) возвращает папку с исполняемым файлом.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """Путь к упакованному ресурсу (иконка и т.п.).

    В onedir-сборке PyInstaller данные лежат в _MEIPASS (папка _internal).
    """
    base = getattr(sys, "_MEIPASS", None) or app_dir()
    return os.path.join(base, name)


def total_files_size_mb(paths: list[str]) -> float:
    """Суммарный размер файлов в МБ (несуществующие файлы пропускаются)."""
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except OSError:
            continue
    return total / (1024 * 1024)


# --- Валидация --------------------------------------------------------------


def is_valid_email(value: str) -> bool:
    """Простая проверка адреса e-mail (используется при подтверждении почты)."""
    return bool(EMAIL_RE.match(value.strip()))


def is_auth_error(exc: Exception) -> bool:
    """Ошибка авторизации (SMTP или WebDAV): пароль не подошёл или устарел.

    По таким ошибкам программа предлагает ввести пароль заново, а не
    «повторить попытку» — повтор бессмыслен, пока секрет не заменён.
    """
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return True
    text = str(exc).lower()
    return "auth" in text or "401" in text or ("login" in text and "password" in text)


def build_password_request_mailto(recipient: str, sender: str) -> str:
    """mailto-ссылка с готовым письмом-запросом пароля администратору.

    Письмо открывается в почтовой программе самого сотрудника: программе
    для этого не нужны никакие секреты (кодов и паролей в exe нет). Пароль
    администратор передаёт сотруднику лично, а не в ответ на письмо.
    """
    subject = "Запрос пароля для программы «КМЦБС Новости»"
    body = (
        "Здравствуйте!\n\n"
        "Настраиваю программу «КМЦБС Новости» для отправки новостей.\n"
        "Пожалуйста, передайте мне пароль облачного аккаунта программы "
        "(он нужен для загрузки файлов в облако и отправки писем).\n\n"
        f"Моя рабочая почта: {sender or '-'}\n\n"
        "Спасибо!"
    )
    return f"mailto:{recipient}?subject={quote(subject)}&body={quote(body)}"


def password_request_letter(sender: str) -> str:
    """Текст письма-запроса пароля (для копирования в буфер обмена).

    Запасной путь, если почтовая программа на машине не настроена:
    текст копируется и отправляется любым доступным способом.
    """
    return (
        "Тема: Запрос пароля для программы «КМЦБС Новости»\n\n"
        "Здравствуйте!\n\n"
        "Настраиваю программу «КМЦБС Новости» для отправки новостей.\n"
        "Пожалуйста, передайте мне пароль облачного аккаунта программы "
        "(он нужен для загрузки файлов в облако и отправки писем).\n\n"
        f"Моя рабочая почта: {sender or '-'}\n\n"
        "Спасибо!"
    )


def validate_submission(
    email: str,
    title: str,
    desc: str,
    placeholder: str,
    files: list[str] | None = None,
) -> str | None:
    """Проверка обязательных полей новости.

    Возвращает текст ошибки для пользователя или None, если всё заполнено.
    """
    email = (email or "").strip()
    title = (title or "").strip()
    desc = (desc or "").strip()
    if not email or not title or not desc or desc == placeholder:
        return "Заполните все обязательные поля!"
    if len(title) > MAX_TITLE_LEN:
        return f"Название слишком длинное: {len(title)} из {MAX_TITLE_LEN} символов."
    if len(desc) > MAX_DESC_LEN:
        return f"Описание слишком длинное: {len(desc)} из {MAX_DESC_LEN} символов."
    if files:
        size_mb = total_files_size_mb(files)
        if size_mb > ATTACH_LIMIT_MB:
            return (f"Слишком большой общий вес вложений: {size_mb:.0f} МБ "
                    f"(лимит {ATTACH_LIMIT_MB} МБ). Удалите часть файлов.")
    return None


def normalize_hashtag(tag: str) -> str:
    """Приводит тег к виду #тег (без пробелов по краям)."""
    tag = tag.strip()
    if tag and not tag.startswith("#"):
        tag = "#" + tag
    return tag


def merge_tag_tokens(field_text: str, tag: str, add: bool) -> str:
    """Добавляет/удаляет тег в строке ручного ввода хештегов (B3).

    Поле обновляется токен-по-токену: вручную набранные теги не затираются
    при клике по чипу.
    """
    tokens = [t for t in field_text.split() if t]
    if add and tag not in tokens:
        tokens.append(tag)
    if not add and tag in tokens:
        tokens.remove(tag)
    return " ".join(tokens)


# --- Прикреплённые файлы ------------------------------------------------------

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def is_image_file(name: str) -> bool:
    """Является ли файл изображением (по расширению) — для миниатюр."""
    return os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS


def human_file_size(size: int) -> str:
    """Размер файла в человекочитаемом виде."""
    size = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


def thumbnail_cache_key(path: str) -> tuple[str, float, int]:
    """Ключ кэша миниатюр: путь + время изменения + размер файла.

    Если файл заменили другим содержимым с тем же именем, миниатюра
    перестроится.
    """
    try:
        st = os.stat(path)
        return (os.path.abspath(path), st.st_mtime, st.st_size)
    except OSError:
        return (os.path.abspath(path), 0.0, 0)


# --- Повтор попыток при сетевых сбоях ----------------------------------------


def with_retries(operation, attempts: int = 3, delay_sec: float = 2.0, what: str = ""):
    """Выполняет операцию с повторами при ошибке (сеть: WebDAV/SMTP).

    Все попытки провалились — поднимает последнее исключение.
    """
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            return operation()
        except Exception as e:
            last_exc = e
            log.warning("Попытка %d/%d не удалась%s: %s", i, attempts, f" ({what})" if what else "", e)
            if i < attempts:
                time.sleep(delay_sec * i)  # растущая пауза: 2с, 4с, ...
    raise last_exc


# --- Проверка обновлений -----------------------------------------------------

UPDATE_CHECK_TIMEOUT_SEC = 8
UPDATE_CACHE_FILENAME = ".update_cache.json"
UPDATE_CACHE_TTL_SEC = 7 * 24 * 3600  # старше — считаем протухшим, только сеть


def _update_cache_path() -> str:
    return os.path.join(app_dir(), UPDATE_CACHE_FILENAME)


def _load_update_cache() -> dict:
    try:
        with open(_update_cache_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_update_cache(cache: dict) -> None:
    """Атомарная запись кэша проверки обновлений (см. save_settings)."""
    path = _update_cache_path()
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp, path)
    except OSError:
        log.debug("Не удалось записать кэш проверки обновлений", exc_info=True)


def _cache_is_fresh(cache: dict) -> bool:
    checked = cache.get("checked_at")
    return (
        isinstance(checked, (int, float))
        and time.time() - checked < UPDATE_CACHE_TTL_SEC
        and bool(cache.get("latest"))
    )


def _atom_tag_titles(body: bytes) -> list[str]:
    """Имена тегов из веб-ленты tags.atom (элементы entry/title)."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    ns = "{http://www.w3.org/2005/Atom}"
    return [(e.text or "").strip() for e in root.findall(f"{ns}entry/{ns}title")]


def fetch_latest_version(repo: str = GITHUB_REPO, timeout: float = UPDATE_CHECK_TIMEOUT_SEC) -> str | None:
    """Последняя версия из веб-ленты тегов GitHub (vX.Y.Z, по убыванию).

    Лента tags.atom, а НЕ api.github.com: анонимный API ограничен
    60 запросами в час НА IP-АДРЕС, а офисы выходят в интернет через
    общий NAT и делят лимит со всем офисом — он почти всегда исчерпан
    (HTTP 403 rate limit). Веб-лента отдаётся сайтом GitHub и таким
    лимитом не обладает. ETag-кэш дополнительно исключает повторные
    запросы. None — сеть недоступна и свежего кэша нет: проверка
    обновлений не должна ломать приложение.
    """
    cache = _load_update_cache()
    headers = {
        # User-Agent обязан быть ASCII: HTTP-заголовки не принимают кириллицу
        # (UnicodeEncodeError ломал проверку обновлений целиком)
        "User-Agent": "KMCBS-News-Update-Check",
        "Accept": "application/atom+xml",
    }
    if cache.get("etag"):
        headers["If-None-Match"] = str(cache["etag"])
    url = f"https://github.com/{repo}/tags.atom"
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as r:
            body = r.read()
            etag = r.headers.get("ETag")
        versions = [v for v in (parse_version(t) for t in _atom_tag_titles(body)) if v is not None]
        latest = ".".join(str(p) for p in max(versions)) if versions else None
        if latest:
            _save_update_cache({"etag": etag, "latest": latest, "checked_at": time.time()})
        return latest
    except HTTPError as e:
        if e.code == 304 and _cache_is_fresh(cache):
            # «Не изменилось» — версия из кэша всё ещё актуальна,
            # лимит GitHub при этом не тратится
            return str(cache["latest"])
        log.info("Проверка обновлений недоступна: HTTP %s", e.code)
        if _cache_is_fresh(cache):
            return str(cache["latest"])  # сеть дохлая — показываем кэш
        return None
    except Exception as e:
        log.info("Проверка обновлений недоступна: %s", e)
        if _cache_is_fresh(cache):
            return str(cache["latest"])
        return None


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v1.2.3' / '1.2.3' -> (1, 2, 3); None если это не версия."""
    m = re.match(r"^v?(\d+(?:\.\d+)*)$", text.strip())
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def is_newer_version(remote: str, current: str) -> bool:
    """ True, если remote строго новее current (сравнение по компонентам)."""
    r = parse_version(remote)
    c = parse_version(current)
    if r is None or c is None:
        return False
    # дополняем короткие версии нулями: 1.2 == 1.2.0
    width = max(len(r), len(c))
    return r + (0,) * (width - len(r)) > c + (0,) * (width - len(c))


# --- Секреты: Windows Credential Manager --------------------------------------

# Пароли (WebDAV/SMTP) хранятся не в config.json открытым текстом, а в
# диспетчере учётных данных Windows — под учётной записью пользователя.
# Значения паролей при этом не меняются, меняется только место хранения.
# На не-Windows или при сбое диспетчера — прозрачный откат в config.json.

SECRET_KEYS = ("webdav_password", "smtp_password")
CRED_TARGET_PREFIX = "КМЦБС_Новости"


def _cred_target(key: str) -> str:
    return f"{CRED_TARGET_PREFIX}/{key}"


def _cred_manager_available() -> bool:
    return sys.platform == "win32"


def store_secret(key: str, value: str) -> bool:
    """Сохраняет секрет в диспетчере учётных данных Windows.

    False — диспетчер недоступен (не Windows / сбой): вызывающий код
    оставит значение в config.json как раньше.
    """
    if not _cred_manager_available():
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wt.DWORD),
                ("Type", wt.DWORD),
                ("TargetName", wt.LPWSTR),
                ("Comment", wt.LPWSTR),
                ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wt.DWORD),
                ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR),
            ]

        blob = value.encode("utf-16-le")
        buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIAL()
        cred.Type = 1  # CRED_TYPE_GENERIC
        cred.TargetName = _cred_target(key)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = ""

        advapi32 = ctypes.windll.advapi32
        if not advapi32.CredWriteW(ctypes.byref(cred), 0):
            return False
        return True
    except Exception:
        log.warning("Не удалось сохранить секрет %s в Credential Manager", key, exc_info=True)
        return False


def load_secret(key: str) -> str | None:
    """Читает секрет из диспетчера учётных данных; None если его там нет."""
    if not _cred_manager_available():
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt

        advapi32 = ctypes.windll.advapi32
        pcred = ctypes.c_void_p()
        if not advapi32.CredReadW(_cred_target(key), 1, 0, ctypes.byref(pcred)):
            return None
        try:
            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ("Flags", wt.DWORD),
                    ("Type", wt.DWORD),
                    ("TargetName", wt.LPWSTR),
                    ("Comment", wt.LPWSTR),
                    ("LastWritten", wt.FILETIME),
                    ("CredentialBlobSize", wt.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", wt.DWORD),
                    ("AttributeCount", wt.DWORD),
                    ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wt.LPWSTR),
                    ("UserName", wt.LPWSTR),
                ]

            cred = ctypes.cast(pcred, ctypes.POINTER(CREDENTIAL)).contents
            size = cred.CredentialBlobSize
            blob = ctypes.string_at(cred.CredentialBlob, size)
            return blob.decode("utf-16-le")
        finally:
            advapi32.CredFree(pcred)
    except Exception:
        log.warning("Не удалось прочитать секрет %s из Credential Manager", key, exc_info=True)
        return None


def delete_secret(key: str) -> None:
    """Удаляет секрет из диспетчера (при очистке настроек)."""
    if not _cred_manager_available():
        return
    try:
        import ctypes

        ctypes.windll.advapi32.CredDeleteW(_cred_target(key), 1, 0)
    except Exception:
        log.debug("Не удалось удалить секрет %s", key, exc_info=True)


def migrate_secrets_to_cred_manager(settings: dict) -> bool:
    """Переносит пароли из config.json в Credential Manager.

    Возвращает True, если после вызова пароли хранятся в диспетчере
    (свежая миграция или они уже там). Значения из config.json при успехе
    затираются — открытого текста в файле больше нет.
    """
    moved = False
    for key in SECRET_KEYS:
        value = settings.get(key)
        if value:  # есть в config.json — переносим
            if store_secret(key, value):
                settings[key] = ""
                moved = True
    if moved:
        log.info("Пароли перенесены из config.json в Windows Credential Manager")
    return moved


# --- Авторизация ------------------------------------------------------------


def generate_verification_code() -> str:
    """6-значный код подтверждения из криптографического генератора.

    Используется secrets вместо random: random предсказуем и не подходит
    для проверочных кодов.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


# --- Отправка новости --------------------------------------------------------


def make_cloud_folder(now: dt.datetime | None = None) -> str:
    """Имя папки новости в облаке: дата-время + случайный суффикс (B9).

    Суффикс исключает коллизии при отправках в одну и ту же секунду.
    """
    ts = (now or dt.datetime.now()).strftime("%d%m%Y-%H%M%S")
    return f"{ts}-{secrets.token_hex(3)}"


def unique_remote_names(paths: list[str]) -> list[str]:
    """Имена файлов для загрузки в облако без коллизий (B8).

    Файлы с одинаковыми именами из разных папок получают суффиксы (1), (2)…,
    чтобы не перезаписывать друг друга в общей папке новости.
    """
    used: set[str] = set()
    result: list[str] = []
    for path in paths:
        base = os.path.basename(path)
        candidate = base
        counter = 1
        while candidate in used:
            stem, ext = os.path.splitext(base)
            candidate = f"{stem}({counter}){ext}"
            counter += 1
        used.add(candidate)
        result.append(candidate)
    return result


def _quote_url_path(url: str) -> str:
    """Кодирует путь в URL: пробелы, кириллица, #, % и т.п. (B10)."""
    scheme, _, rest = url.partition("://")
    domain, slash, path = rest.partition("/")
    if not slash:
        return url
    return f"{scheme}://{domain}/{quote(path)}"


def public_file_url(webdav_base: str, folder: str, name: str) -> str:
    """Публичная ссылка на файл в облаке Mail.ru с URL-кодированием."""
    raw = f"{webdav_base.rstrip('/')}/{folder}/{name}"
    url = raw.replace("https://webdav.cloud.mail.ru/", "https://cloud.mail.ru/home/")
    return _quote_url_path(url)


def cloud_folder_link(folder: str) -> str:
    """Публичная ссылка на папку новости с URL-кодированием."""
    return _quote_url_path(f"https://cloud.mail.ru/home/{folder}")


def header_safe(value: str) -> str:
    """Тема письма без переносов строк (защита заголовков письма)."""
    return " ".join(str(value).split())


def build_report_html(
    title: str,
    age_rating: str,
    desc: str,
    branch: str,
    tags: str,
    folder_link: str,
    file_links: list[tuple[str, str]],
    social_links: dict[str, str],
    active_socials: list[str],
    author_email: str,
) -> str:
    """HTML-письмо для администратора.

    Все пользовательские данные экранируются (S6): заголовок, описание,
    филиал, хештеги, имена файлов и e-mail не могут внедрить разметку
    в письмо.

    Переносы строк в описании сохраняются (<br>): стих столбиком
    доходит столбиком, а не сплошным текстом. Соцсети без галочки
    показываются красными (не исчезают) — сразу видно, куда новость
    НЕ ушла.
    """
    esc = html.escape

    def social_chip(net: str, active: bool) -> str:
        if active:
            return (f'<a href="{social_links[net]}" style="display:inline-block;margin:5px;'
                    f'padding:10px 20px;background-color:#0d6efd;color:white;text-decoration:none;'
                    f'border-radius:5px;">{esc(net)}</a>')
        return (f'<span style="display:inline-block;margin:5px;padding:10px 20px;'
                f'background-color:#dc3545;color:white;border-radius:5px;'
                f'text-decoration:line-through;">{esc(net)}</span>')

    buttons = "".join(
        social_chip(net, net in active_socials)
        for net in social_links
    )
    items = "".join(f"<li><a href='{url}'>{esc(name)}</a></li>" for url, name in file_links)
    # \r\n и \r нормализуем, иначе <br> задвоится
    desc_html = esc(desc).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return (
        f"<html><body style='font-family: Arial, sans-serif; color: #333;'>"
        f"<h3>{esc(title)} ({esc(age_rating)})</h3>"
        f"<p style='line-height:1.6;'>{desc_html}</p>"
        f"<p><i>Автор: {esc(branch)}</i></p>"
        f"<p style='color: #0d6efd;'>{esc(tags)}</p>"
        f"<div style='border:1px solid #ddd;padding:15px;margin-top:20px;border-radius:8px;background-color:#f9f9f9;'>"
        f"<p>📂 <a href='{folder_link}'>Папка новости в облаке</a></p>"
        f"<ul>{items}</ul>"
        f"<p>🌐 <b>Публикация:</b></p><p>{buttons}</p>"
        f"<hr style='border:0;border-top:1px solid #eee;margin-top:20px;'>"
        f"<p style='font-size:12px;color:#777;'><i>Связь с автором: "
        f"<a href='mailto:{esc(author_email)}'>{esc(author_email)}</a><br>"
        f"Если в новости есть ошибки, ответьте на этот адрес.</i></p></div></body></html>"
    )


# --- Настройки (config.json) ------------------------------------------------


def merge_defaults(saved: object, defaults: dict) -> dict:
    """Сливает сохранённые настройки с дефолтами.

    Дефолт подставляется, если ключа нет, значение — пустая строка
    или тип повреждён (например, список хештегов превратился в строку).
    """
    merged = dict(defaults)
    if isinstance(saved, dict):
        merged.update(saved)
    for key, default in defaults.items():
        value = merged.get(key)
        if isinstance(default, list) and not isinstance(value, list):
            merged[key] = default
        elif (
            isinstance(default, str)
            and isinstance(value, str)
            and not value.strip()
            and default.strip()
        ):
            merged[key] = default
    return merged


def load_settings(path: str, defaults: dict) -> tuple[dict, str | None]:
    """Читает config.json.

    При повреждении файла сохраняет его копию (чтобы не потерять черновики
    и историю) и возвращает настройки по умолчанию.

    Возвращает кортеж (настройки, путь к бэкапу или None).
    """
    if not os.path.exists(path):
        return dict(defaults), None
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        backup = _backup_corrupt(path)
        log.warning("Файл настроек повреждён (%s), бэкап: %s", exc, backup)
        return dict(defaults), backup
    return merge_defaults(saved, defaults), None


def _backup_corrupt(path: str) -> str | None:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.corrupt-{stamp}"
    try:
        shutil.copy2(path, backup)
        return backup
    except OSError:
        return None


def save_settings(settings: dict, path: str) -> None:
    """Атомарно записывает настройки: сначала во временный файл, затем замена.

    Защищает config.json от частичной записи (например, при выключении ПК).
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
