from bot.md.parser import parse
from bot.md.rich import blocks_to_rich, emoji_mosaic_block


def _render(src: str):
    return blocks_to_rich(parse(src))


def test_plain_paragraph():
    out = _render("hello world")
    assert out == {
        "blocks": [{
            "type": "paragraph",
            "content": [{"type": "text", "text": "hello world"}],
        }],
    }


def test_heading_level():
    out = _render("## Title")
    [b] = out["blocks"]
    assert b["type"] == "section_heading"
    assert b["level"] == 2
    assert b["content"] == [{"type": "text", "text": "Title"}]


def test_bold_italic_styles_emit_on_run():
    out = _render("hello *bold* and _it_ end")
    runs = out["blocks"][0]["content"]
    # Expected: text, bold-text, text, italic-text, text
    assert runs[0] == {"type": "text", "text": "hello "}
    assert runs[1] == {"type": "text", "text": "bold", "styles": ["bold"]}
    assert runs[2] == {"type": "text", "text": " and "}
    assert runs[3] == {"type": "text", "text": "it", "styles": ["italic"]}
    assert runs[4] == {"type": "text", "text": " end"}


def test_nested_styles_merge_into_styles_list():
    out = _render("_outer *inner* tail_")
    runs = out["blocks"][0]["content"]
    # all three runs are italic; middle one is also bold
    assert runs[0] == {"type": "text", "text": "outer ", "styles": ["italic"]}
    assert runs[1] == {
        "type": "text", "text": "inner", "styles": ["bold", "italic"],
    }
    assert runs[2] == {"type": "text", "text": " tail", "styles": ["italic"]}


def test_inline_code_is_its_own_run_without_styles():
    out = _render("a *b `c` d* e")
    runs = out["blocks"][0]["content"]
    # Find the code run
    codes = [r for r in runs if r["type"] == "code"]
    assert codes == [{"type": "code", "text": "c"}]


def test_link_renders_as_url_run_with_url_field():
    out = _render("see [docs](https://x.io/a)")
    runs = out["blocks"][0]["content"]
    assert runs[-1] == {
        "type": "url", "text": "docs", "url": "https://x.io/a",
    }


def test_link_with_bold_inside():
    out = _render("[*loud*](https://x)")
    runs = out["blocks"][0]["content"]
    assert runs == [{
        "type": "url", "text": "loud", "url": "https://x", "styles": ["bold"],
    }]


def test_coalesce_adjacent_same_style_runs():
    # Two bold spans separated by parser only because emphasis closes/reopens
    # — we want the renderer to merge them when they're contiguous AND share
    # styles. Here we just verify two distinct adjacent text runs with same
    # styles get merged.
    out = _render("*a**b*")  # parses as Bold(a) followed by Bold(b)
    runs = out["blocks"][0]["content"]
    assert runs == [{"type": "text", "text": "ab", "styles": ["bold"]}]


def test_blockquote_and_pullquote():
    out = blocks_to_rich(parse("> quote\n\n>> pulled"))
    kinds = [b["type"] for b in out["blocks"]]
    assert kinds == ["block_quotation", "pull_quotation"]


def test_codeblock_with_language():
    out = _render("```python\nprint(1)\n```")
    [b] = out["blocks"]
    assert b == {"type": "preformatted", "text": "print(1)", "language": "python"}


def test_codeblock_without_language():
    out = _render("```\nplain\n```")
    [b] = out["blocks"]
    assert b == {"type": "preformatted", "text": "plain"}


def test_list_block():
    out = _render("- a\n- b *c*")
    [b] = out["blocks"]
    assert b["type"] == "list"
    assert b["ordered"] is False
    assert b["items"][0]["content"] == [{"type": "text", "text": "a"}]
    assert b["items"][1]["content"] == [
        {"type": "text", "text": "b "},
        {"type": "text", "text": "c", "styles": ["bold"]},
    ]


def test_divider():
    out = _render("a\n\n---\n\nb")
    assert out["blocks"][1] == {"type": "divider"}


def test_plain_image_block():
    out = _render("![cover](photo.jpg)")
    [b] = out["blocks"]
    assert b == {
        "type": "photo", "src": "photo.jpg",
        "caption": [{"type": "text", "text": "cover"}],
    }


def test_emoji_marker_image_is_left_for_later_expansion():
    # Emoji markers come out as a photo block too — compose.py is the layer
    # that replaces them with custom_emoji runs once tiles are uploaded.
    out = _render("![[emoji:3x3]](logo.png)")
    [b] = out["blocks"]
    assert b["type"] == "photo"
    assert b["src"] == "logo.png"


# ---------- emoji_mosaic_block ----------

def test_emoji_mosaic_block_shape():
    ids = [f"id{i}" for i in range(6)]  # 3x2 grid
    block = emoji_mosaic_block(cols=3, rows=2, custom_emoji_ids=ids)
    assert block["type"] == "paragraph"
    runs = block["content"]
    # 3 emoji + \n + 3 emoji
    assert len(runs) == 7
    assert runs[3] == {"type": "text", "text": "\n"}
    for r in (runs[0], runs[1], runs[2], runs[4], runs[5], runs[6]):
        assert r["type"] == "custom_emoji"
        assert r["text"] == "⬜"
    assert [r["custom_emoji_id"] for r in runs if r["type"] == "custom_emoji"] == ids


def test_emoji_mosaic_block_size_mismatch():
    import pytest
    with pytest.raises(ValueError):
        emoji_mosaic_block(cols=2, rows=2, custom_emoji_ids=["a", "b"])
