import os
import shutil
import tempfile

import core


def test_is_image_file():
    assert core.is_image_file("photo.JPG")       # регистр не важен
    assert core.is_image_file("a/b/фото.png")
    assert core.is_image_file("anim.gif")
    assert core.is_image_file("pic.webp")
    assert core.is_image_file("scan.bmp")
    assert not core.is_image_file("doc.pdf")
    assert not core.is_image_file("report.docx")
    assert not core.is_image_file("archive.zip")
    assert not core.is_image_file("noext")


def test_human_file_size():
    assert core.human_file_size(0) == "0 Б"
    assert core.human_file_size(999) == "999 Б"
    assert core.human_file_size(1024) == "1.0 КБ"
    assert core.human_file_size(1536) == "1.5 КБ"
    assert core.human_file_size(5 * 1024 * 1024) == "5.0 МБ"
    assert core.human_file_size(3 * 1024 * 1024 * 1024) == "3.0 ГБ"


def _tmp_file(name: str, content: bytes) -> str:
    d = tempfile.mkdtemp(prefix="nad_files_")
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(content)
    return p


def test_thumbnail_cache_key_stable():
    p = _tmp_file("img.png", b"12345")
    k1 = core.thumbnail_cache_key(p)
    k2 = core.thumbnail_cache_key(p)
    assert k1 == k2
    shutil.rmtree(os.path.dirname(p), ignore_errors=True)


def test_thumbnail_cache_key_changes_with_content():
    p = _tmp_file("img.png", b"12345")
    k1 = core.thumbnail_cache_key(p)
    with open(p, "wb") as f:
        f.write(b"1234567890")  # другой размер — другой ключ
    k2 = core.thumbnail_cache_key(p)
    assert k1 != k2
    shutil.rmtree(os.path.dirname(p), ignore_errors=True)


def test_thumbnail_cache_key_missing_file():
    k = core.thumbnail_cache_key(os.path.join(tempfile.gettempdir(), "nad_missing_file.png"))
    assert k[1:] == (0.0, 0)
