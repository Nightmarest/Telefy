from bot.md.escape import escape_code, escape_link_url, escape_text


def test_escape_text_specials():
    assert escape_text("Hello, world!") == "Hello, world\\!"
    assert escape_text("a.b.c") == "a\\.b\\.c"
    assert escape_text("1+1=2") == "1\\+1\\=2"


def test_escape_text_brackets_and_pipes():
    assert escape_text("[link](url)") == "\\[link\\]\\(url\\)"
    assert escape_text("a|b") == "a\\|b"
    assert escape_text("{x}") == "\\{x\\}"


def test_escape_text_plain_letters_untouched():
    assert escape_text("abcXYZабв09") == "abcXYZабв09"


def test_escape_code_only_backtick_and_backslash():
    assert escape_code("a`b") == "a\\`b"
    assert escape_code("a\\b") == "a\\\\b"
    # specials that are escaped in body text stay raw inside code
    assert escape_code("1+1=2!") == "1+1=2!"


def test_escape_link_url():
    assert escape_link_url("https://x.io/a(b)c") == "https://x.io/a(b\\)c"
    assert escape_link_url("a\\b") == "a\\\\b"
