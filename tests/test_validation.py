import core


def test_is_valid_email():
    assert core.is_valid_email("user@mail.ru")
    assert core.is_valid_email("  user@mail.ru  ")
    assert not core.is_valid_email("")
    assert not core.is_valid_email("a@")
    assert not core.is_valid_email("a b@mail.ru")
    assert not core.is_valid_email("a@mail")
    assert not core.is_valid_email("mail.ru")


def test_validate_submission():
    assert core.validate_submission("a@mail.ru", "Заголовок", "Текст", "Описание") is None
    # не подтверждён email
    assert core.validate_submission("", "Заголовок", "Текст", "Описание")
    # пустой заголовок
    assert core.validate_submission("a@mail.ru", "   ", "Текст", "Описание")
    # пустое описание
    assert core.validate_submission("a@mail.ru", "Заголовок", "", "Описание")
    # в описании остался неубранный плейсхолдер
    assert core.validate_submission("a@mail.ru", "Заголовок", "Описание", "Описание")


def test_normalize_hashtag():
    assert core.normalize_hashtag("тизер") == "#тизер"
    assert core.normalize_hashtag("#тизер") == "#тизер"
    assert core.normalize_hashtag("  #тизер  ") == "#тизер"
    assert core.normalize_hashtag("") == ""
    assert core.normalize_hashtag("   ") == ""


def test_merge_tag_tokens_add_and_remove():
    assert core.merge_tag_tokens("#а #б", "#в", True) == "#а #б #в"
    assert core.merge_tag_tokens("#а #б #в", "#б", False) == "#а #в"
    # добавление уже существующего тега не создаёт дубликат
    assert core.merge_tag_tokens("#а #б", "#а", True) == "#а #б"
    assert core.merge_tag_tokens("", "#новый", True) == "#новый"
    # лишние пробелы нормализуются
    assert core.merge_tag_tokens("  #а   #б  ", "#в", True) == "#а #б #в"
    # удаление отсутствующего тега ничего не меняет
    assert core.merge_tag_tokens("#а", "#я", False) == "#а"
