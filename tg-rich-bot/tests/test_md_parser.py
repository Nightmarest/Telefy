from bot.md.parser import (
    Bold, BlockQuote, Code, CodeBlock, Divider, Heading, Image, InlineImage,
    Italic, Link, ListBlock, Paragraph, PullQuote, Spoiler, Strike, Text,
    Underline, parse,
)


# ---------- block-level ----------

def test_single_paragraph():
    [b] = parse("Hello world")
    assert isinstance(b, Paragraph)
    assert b.inlines == [Text("Hello world")]


def test_paragraphs_separated_by_blank_line():
    blocks = parse("first\n\nsecond")
    assert len(blocks) == 2
    assert all(isinstance(b, Paragraph) for b in blocks)
    assert blocks[0].inlines == [Text("first")]
    assert blocks[1].inlines == [Text("second")]


def test_multiline_paragraph_joins_with_space():
    [b] = parse("a\nb\nc")
    assert isinstance(b, Paragraph)
    assert b.inlines == [Text("a b c")]


def test_headings_levels():
    blocks = parse("# H1\n## H2\n### H3\n#### still H3")
    assert [b.level for b in blocks] == [1, 2, 3, 3]  # type: ignore[attr-defined]
    assert all(isinstance(b, Heading) for b in blocks)


def test_divider():
    blocks = parse("a\n\n---\n\nb")
    assert isinstance(blocks[1], Divider)


def test_blockquote_collapses_lines():
    [b] = parse("> first\n> second")
    assert isinstance(b, BlockQuote)
    assert b.inlines == [Text("first second")]


def test_pullquote_distinct_from_blockquote():
    [b] = parse(">> highlight")
    assert isinstance(b, PullQuote)


def test_unordered_list():
    [b] = parse("- one\n- two\n- three")
    assert isinstance(b, ListBlock) and not b.ordered
    assert [item[0].value for item in b.items] == ["one", "two", "three"]  # type: ignore[attr-defined]


def test_ordered_list():
    [b] = parse("1. one\n2. two")
    assert isinstance(b, ListBlock) and b.ordered
    assert len(b.items) == 2


def test_code_block_with_lang():
    [b] = parse("```python\nprint(1)\nprint(2)\n```")
    assert isinstance(b, CodeBlock)
    assert b.lang == "python"
    assert b.value == "print(1)\nprint(2)"


def test_code_block_preserves_specials():
    [b] = parse("```\n*not bold* _not italic_\n```")
    assert isinstance(b, CodeBlock)
    assert b.value == "*not bold* _not italic_"


def test_standalone_image():
    [b] = parse("![alt text](photo.jpg)")
    assert isinstance(b, Image)
    assert b.alt == "alt text"
    assert b.src == "photo.jpg"
    assert b.emoji is None


def test_emoji_marker_image():
    [b] = parse("![[emoji:6x4]](pic.png)")
    assert isinstance(b, Image)
    assert b.emoji == (6, 4)
    assert b.alt == ""
    assert b.src == "pic.png"


def test_mixed_document():
    src = (
        "# Title\n"
        "\n"
        "intro paragraph with *bold*.\n"
        "\n"
        "![cover](cover.jpg)\n"
        "\n"
        "- a\n"
        "- b\n"
        "\n"
        "```rust\nfn main() {}\n```\n"
        "\n"
        "![[emoji:3x3]](logo.png)\n"
    )
    blocks = parse(src)
    kinds = [type(b).__name__ for b in blocks]
    assert kinds == ["Heading", "Paragraph", "Image", "ListBlock", "CodeBlock", "Image"]
    assert blocks[-1].emoji == (3, 3)  # type: ignore[attr-defined]


# ---------- inline ----------

def _inlines(src: str):
    [b] = parse(src)
    assert isinstance(b, Paragraph)
    return b.inlines


def test_inline_bold():
    inl = _inlines("hello *world*")
    assert inl[0] == Text("hello ")
    assert isinstance(inl[1], Bold)
    assert inl[1].children == [Text("world")]


def test_inline_italic_and_underline():
    inl = _inlines("_em_ vs __under__")
    assert isinstance(inl[0], Italic)
    assert isinstance(inl[2], Underline)


def test_inline_strike_and_spoiler():
    inl = _inlines("~gone~ and ||hidden||")
    assert isinstance(inl[0], Strike)
    assert isinstance(inl[2], Spoiler)


def test_inline_code_keeps_specials():
    inl = _inlines("run `*starred*`")
    assert isinstance(inl[1], Code)
    assert inl[1].value == "*starred*"


def test_link_basic():
    inl = _inlines("see [docs](https://example.com/x)")
    link = inl[1]
    assert isinstance(link, Link)
    assert link.url == "https://example.com/x"
    assert link.children == [Text("docs")]


def test_link_with_formatting_inside():
    inl = _inlines("[*loud*](https://x)")
    link = inl[0]
    assert isinstance(link, Link)
    assert isinstance(link.children[0], Bold)


def test_inline_image_in_paragraph():
    inl = _inlines("before ![cap](a.png) after")
    img = inl[1]
    assert isinstance(img, InlineImage)
    assert img.src == "a.png" and img.emoji is None


def test_inline_emoji_marker():
    inl = _inlines("look ![[emoji:2x2]](tiny.png)!")
    img = inl[1]
    assert isinstance(img, InlineImage)
    assert img.emoji == (2, 2)


def test_escaped_specials():
    inl = _inlines(r"a \*not bold\* b")
    # Backslash escapes collapse into the buffer → no Bold node
    assert len(inl) == 1
    assert isinstance(inl[0], Text)
    assert inl[0].value == "a *not bold* b"


def test_nested_bold_in_italic():
    inl = _inlines("_outer *inner* tail_")
    it = inl[0]
    assert isinstance(it, Italic)
    assert isinstance(it.children[1], Bold)


def test_blockquote_with_inline_formatting():
    [b] = parse("> read *this* now")
    assert isinstance(b, BlockQuote)
    assert isinstance(b.inlines[1], Bold)


def test_list_item_with_inline_formatting():
    [b] = parse("- buy `milk`\n- and *bread*")
    assert isinstance(b, ListBlock)
    assert isinstance(b.items[0][1], Code)
    assert isinstance(b.items[1][1], Bold)
