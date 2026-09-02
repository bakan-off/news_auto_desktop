import re

import core

SOCIALS = {
    "Сайт": "https://example.ru/site",
    "ВК": "https://vk.com/x",
    "Telegram": "https://t.me/x",
}


def test_make_cloud_folder_format():
    folder = core.make_cloud_folder()
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", folder)


def test_make_cloud_folder_unique():
    folders = {core.make_cloud_folder() for _ in range(20)}
    assert len(folders) == 20


def test_unique_remote_names_passthrough():
    paths = [r"C:\a\photo.jpg", r"C:\b\doc.pdf"]
    assert core.unique_remote_names(paths) == ["photo.jpg", "doc.pdf"]


def test_unique_remote_names_dedup():
    # одинаковые имена из разных папок не должны перезаписывать друг друга
    paths = [r"C:\a\отчёт.pdf", r"D:\other\отчёт.pdf", r"E:\third\отчёт.pdf"]
    names = core.unique_remote_names(paths)
    assert len(names) == 3
    assert len(set(names)) == 3
    assert names[0] == "отчёт.pdf"
    assert names[1] == "отчёт(1).pdf"
    assert names[2] == "отчёт(2).pdf"


def test_public_file_url_encodes_spaces_and_unicode():
    url = core.public_file_url(
        "https://webdav.cloud.mail.ru", "01092026-171500-abc123", " фото №1.jpg"
    )
    assert url.startswith("https://cloud.mail.ru/home/01092026-171500-abc123/")
    assert " " not in url
    assert "%20" in url  # пробел закодирован


def test_cloud_folder_link():
    link = core.cloud_folder_link("01092026-171500-abc123")
    assert link == "https://cloud.mail.ru/home/01092026-171500-abc123"


def test_header_safe_collapses_newlines():
    assert core.header_safe("Заголовок\nс переносом\tи табом") == "Заголовок с переносом и табом"


# --- филиал «Не указывать» (v1.6.0) -------------------------------------------


def test_news_subject_with_branch():
    assert core.news_subject("Заголовок", "Луговская библиотека-филиал №5") == \
        "Новость: Заголовок (Луговская библиотека-филиал №5)"


def test_news_subject_without_branch():
    """Без филиала — без скобок: «(Не указывать)» в теме было бы мусором."""
    assert core.news_subject("Заголовок", core.BRANCH_NOT_SPECIFIED) == "Новость: Заголовок"
    assert core.news_subject("Заголовок", "") == "Новость: Заголовок"
    assert "Не указывать" not in core.news_subject("Заголовок", core.BRANCH_NOT_SPECIFIED)


def test_report_branch_unspecified():
    """Без филиала строки «Автор:» в письме нет вообще (v1.6.1).

    Прежний вариант честно писал «филиал не указан», но живой тест
    показал: служебная строка в письме не нужна — письмо без филиала
    просто не содержит строки автора.
    """
    html_out = core.build_report_html(
        title="Т",
        age_rating="0+",
        desc="Д",
        branch=core.BRANCH_NOT_SPECIFIED,
        tags="",
        folder_link="https://cloud.mail.ru/home/f-1",
        file_links=[],
        social_links=SOCIALS,
        active_socials=[],
        author_email="a@b.ru",
    )
    assert "Автор:" not in html_out
    assert "филиал не указан" not in html_out
    assert "Не указывать" not in html_out


def test_report_branch_normal():
    html_out = core.build_report_html(
        title="Т",
        age_rating="0+",
        desc="Д",
        branch="Луговская библиотека-филиал №5",
        tags="",
        folder_link="https://cloud.mail.ru/home/f-1",
        file_links=[],
        social_links=SOCIALS,
        active_socials=[],
        author_email="a@b.ru",
    )
    assert "Автор: Луговская библиотека-филиал №5" in html_out


def test_build_report_html_escapes_user_content():
    html_out = core.build_report_html(
        title="<script>alert(1)</script>",
        age_rating="0+",
        desc='Текст с <b>разметкой</b> и "кавычками"',
        branch="Филиал & отдел",
        tags="#тег <img src=x>",
        folder_link=core.cloud_folder_link("folder-1"),
        file_links=[("https://cloud.mail.ru/home/f/file.jpg", "файл <1>.jpg")],
        social_links=SOCIALS,
        active_socials=["ВК"],
        author_email="a@b.ru",
    )
    # разметка пользователя экранирована и не попадает в письмо как HTML
    assert "<script>" not in html_out
    assert "<img src=x>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "&lt;b&gt;" in html_out  # пользовательский <b> экранирован
    assert "alert(1)" in html_out  # сам текст сохранён
    # выбранная соцсеть — синяя кнопка со ссылкой
    assert "https://vk.com/x" in html_out
    assert "mailto:a@b.ru" in html_out


def test_build_report_html_inactive_socials_red():
    """Соцсети без галочки не исчезают: красные перечёркнутые, без ссылки."""
    html_out = core.build_report_html(
        title="Т",
        age_rating="0+",
        desc="Д",
        branch="Ф",
        tags="",
        folder_link="https://cloud.mail.ru/home/f-1",
        file_links=[],
        social_links=SOCIALS,
        active_socials=["ВК"],
        author_email="a@b.ru",
    )
    # активная — ссылка
    assert "https://vk.com/x" in html_out
    # неактивные: имя видно, красная плашка, но БЕЗ ссылки
    assert ">Сайт<" in html_out and ">Telegram<" in html_out
    assert "https://example.ru/site" not in html_out
    assert "https://t.me/x" not in html_out
    red_span = re.search(r"<span[^>]*>Telegram</span>", html_out)
    assert red_span and "#dc3545" in red_span.group(0)
    assert "line-through" in red_span.group(0)


def test_build_report_html_preserves_line_breaks():
    """Стих столбиком доходит столбиком: \\n -> <br> (и нет задвоения для \\r\\n)."""
    html_out = core.build_report_html(
        title="Стих",
        age_rating="0+",
        desc="Строка один\nСтрока два\r\nСтрока три",
        branch="Ф",
        tags="",
        folder_link="https://cloud.mail.ru/home/f-1",
        file_links=[],
        social_links=SOCIALS,
        active_socials=[],
        author_email="a@b.ru",
    )
    assert "Строка один<br>Строка два<br>Строка три" in html_out
    assert "<br><br>" not in html_out  # \r\n не даёт двойной <br>
    assert "\nСтрока" not in html_out.split("<body")[1].split("</p>")[0]  # сырых \n в абзаце нет


def test_build_report_html_includes_files_and_folder():
    html_out = core.build_report_html(
        title="Т",
        age_rating="6+",
        desc="Д",
        branch="Ф",
        tags="",
        folder_link="https://cloud.mail.ru/home/f-1",
        file_links=[("https://cloud.mail.ru/home/f-1/a.jpg", "a.jpg")],
        social_links=SOCIALS,
        active_socials=[],
        author_email="a@b.ru",
    )
    assert "https://cloud.mail.ru/home/f-1/a.jpg" in html_out
    assert ">a.jpg<" in html_out
