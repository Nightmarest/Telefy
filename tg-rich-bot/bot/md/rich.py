"""Render parsed Block tree → Telegram Bot API 10.1 RichMessage JSON.

Bot API 10.1 (June 2026) introduced `sendRichMessage` and
`InputRichMessageContent`. Per the docs, RichMessage payloads are made of
*rich blocks* (Paragraph, SectionHeading, Preformatted, BlockQuotation,
PullQuotation, List, Divider, Photo, Collage, Slideshow, …) where each
text-bearing block carries *rich text* elements (Bold, Italic, Underline,
Strikethrough, Spoiler, Code, Url, CustomEmoji, plain text runs, …).

The exact JSON keys aren't fully pinned down in the public docs yet, so
we build a single small `_RichBuilder` that emits a shape consistent with
the documented `RichBlock*` / `RichText*` class names. If Telegram tweaks
the wire format later we only touch this file.

Wire-format conventions used here (best effort from the public docs):
  block:    {"type": "<rich_block_kind>", ...}
  text run: {"type": "<rich_text_kind>", "text": "...", ...}
  a text-bearing block has a "content" array of text runs.

Custom-emoji runs are emitted as
  {"type": "custom_emoji", "text": "<placeholder>", "custom_emoji_id": "..."}
which matches the existing MessageEntity convention.
"""
from __future__ import annotations

from typing import Any

from .parser import (
    Block, Bold, BlockQuote, Code, CodeBlock, Divider, Heading, Image,
    Inline, InlineImage, Italic, Link, ListBlock, Paragraph, PullQuote,
    Spoiler, Strike, Text, Underline,
)


def blocks_to_rich(blocks: list[Block]) -> dict[str, Any]:
    """Build an `InputRichMessageContent`-shaped dict.

    Returns a dict ready to be JSON-serialized as the `rich_message`
    parameter of `sendRichMessage`.
    """
    out_blocks: list[dict[str, Any]] = []
    for b in blocks:
        rendered = _render_block(b)
        if rendered is not None:
            out_blocks.append(rendered)
    return {"blocks": out_blocks}


# ---------- block dispatch ----------

def _render_block(b: Block) -> dict[str, Any] | None:
    if isinstance(b, Paragraph):
        return {"type": "paragraph", "content": _render_inlines(b.inlines)}

    if isinstance(b, Heading):
        return {
            "type": "section_heading",
            "level": b.level,
            "content": _render_inlines(b.inlines),
        }

    if isinstance(b, BlockQuote):
        return {"type": "block_quotation", "content": _render_inlines(b.inlines)}

    if isinstance(b, PullQuote):
        return {"type": "pull_quotation", "content": _render_inlines(b.inlines)}

    if isinstance(b, CodeBlock):
        block: dict[str, Any] = {"type": "preformatted", "text": b.value}
        if b.lang:
            block["language"] = b.lang
        return block

    if isinstance(b, Divider):
        return {"type": "divider"}

    if isinstance(b, ListBlock):
        return {
            "type": "list",
            "ordered": b.ordered,
            "items": [
                {"content": _render_inlines(item)} for item in b.items
            ],
        }

    if isinstance(b, Image):
        return _render_image_block(b)

    raise TypeError(f"unsupported block type: {type(b).__name__}")


def _render_image_block(img: Image) -> dict[str, Any]:
    """Image block.

    Real photo sourcing (file_id / URL / multipart upload) is wired up
    in handlers/compose.py once we know whether it came from an album,
    a URL, or an emoji marker. Here we emit a placeholder block with the
    source verbatim — `compose.py` will rewrite `src` into the right
    InputFile reference before sending.

    Emoji-marker images are turned into a `paragraph` of custom_emoji
    runs by `attach_emoji_mosaic` below; this function is only called
    for plain images.
    """
    block: dict[str, Any] = {"type": "photo", "src": img.src}
    if img.alt:
        block["caption"] = [{"type": "text", "text": img.alt}]
    return block


# ---------- inline runs ----------

def _render_inlines(items: list[Inline]) -> list[dict[str, Any]]:
    """Flatten the inline tree into a sequence of styled text runs.

    RichText runs in Bot API 10.1 don't nest like our AST does, so we
    walk the tree, carry the set of active styles down, and emit one run
    per contiguous styled segment.
    """
    out: list[dict[str, Any]] = []
    _walk(items, frozenset(), out, link=None)
    return _coalesce(out)


# style names mirror the documented RichText* kinds; we just OR them into
# a list on each run.
_STYLE_BOLD = "bold"
_STYLE_ITALIC = "italic"
_STYLE_UNDERLINE = "underline"
_STYLE_STRIKE = "strikethrough"
_STYLE_SPOILER = "spoiler"


def _walk(
    items: list[Inline],
    styles: frozenset[str],
    out: list[dict[str, Any]],
    *,
    link: str | None,
) -> None:
    for node in items:
        if isinstance(node, Text):
            out.append(_styled_run(node.value, styles, link))
        elif isinstance(node, Bold):
            _walk(node.children, styles | {_STYLE_BOLD}, out, link=link)
        elif isinstance(node, Italic):
            _walk(node.children, styles | {_STYLE_ITALIC}, out, link=link)
        elif isinstance(node, Underline):
            _walk(node.children, styles | {_STYLE_UNDERLINE}, out, link=link)
        elif isinstance(node, Strike):
            _walk(node.children, styles | {_STYLE_STRIKE}, out, link=link)
        elif isinstance(node, Spoiler):
            _walk(node.children, styles | {_STYLE_SPOILER}, out, link=link)
        elif isinstance(node, Code):
            # Inline code is its own atomic run — styles don't apply inside.
            run: dict[str, Any] = {"type": "code", "text": node.value}
            out.append(run)
        elif isinstance(node, Link):
            _walk(node.children, styles, out, link=node.url)
        elif isinstance(node, InlineImage):
            # Plain inline images don't really fit RichText (no inline
            # image RichText kind exists per the docs). We emit a
            # placeholder run that compose.py can later swap, or drop
            # silently for emoji markers (those get expanded to
            # custom_emoji runs separately).
            if node.emoji is None:
                out.append(_styled_run(f"[image:{node.src}]", styles, link))
            # emoji-marker inline images are deferred — see expand_emoji_runs
        else:
            raise TypeError(f"unsupported inline node: {type(node).__name__}")


def _styled_run(
    text: str, styles: frozenset[str], link: str | None,
) -> dict[str, Any]:
    if not text:
        return {"type": "text", "text": ""}
    if link is not None:
        run: dict[str, Any] = {"type": "url", "text": text, "url": link}
    else:
        run = {"type": "text", "text": text}
    if styles:
        # Sorted for determinism in tests.
        run["styles"] = sorted(styles)
    return run


def _coalesce(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent runs that share type + styles + link."""
    if not runs:
        return runs
    out: list[dict[str, Any]] = [runs[0]]
    for r in runs[1:]:
        prev = out[-1]
        if (
            r.get("type") == prev.get("type") == "text"
            and r.get("styles") == prev.get("styles")
        ):
            prev["text"] = prev.get("text", "") + r.get("text", "")
            continue
        if (
            r.get("type") == prev.get("type") == "url"
            and r.get("url") == prev.get("url")
            and r.get("styles") == prev.get("styles")
        ):
            prev["text"] = prev.get("text", "") + r.get("text", "")
            continue
        out.append(r)
    return out


# ---------- custom-emoji helpers (used by handlers/compose later) ----------

def emoji_mosaic_block(
    cols: int, rows: int, custom_emoji_ids: list[str], *, placeholder: str = "⬜",
) -> dict[str, Any]:
    """Build a single `paragraph` block carrying a rows×cols grid of
    custom_emoji runs interleaved with `\\n` separators.

    `custom_emoji_ids` must be in row-major order, length == cols*rows.
    """
    expected = cols * rows
    if len(custom_emoji_ids) != expected:
        raise ValueError(
            f"expected {expected} emoji ids for {cols}x{rows} mosaic, "
            f"got {len(custom_emoji_ids)}"
        )
    runs: list[dict[str, Any]] = []
    for r in range(rows):
        for c in range(cols):
            runs.append({
                "type": "custom_emoji",
                "text": placeholder,
                "custom_emoji_id": custom_emoji_ids[r * cols + c],
            })
        if r != rows - 1:
            runs.append({"type": "text", "text": "\n"})
    return {"type": "paragraph", "content": runs}
