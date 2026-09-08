"""MarkdownV2 → structured block tree.

We don't try to be CommonMark — just the subset that maps cleanly onto
Telegram Bot API 10.1 RichMessage blocks. The parser produces a list of
`Block` dataclasses; rendering into the JSON `InputRichMessageContent`
payload lives in `bot.md.rich`.

Supported block constructs:
  - `# H1` / `## H2` / `### H3`            → Heading(level)
  - `> quoted line` / `>> pull-quoted`     → BlockQuote / PullQuote
  - ```` ```lang ... ``` ````              → CodeBlock(lang)
  - `- item` / `* item` / `1. item`        → ListBlock(ordered, items)
  - `---` / `***` on its own line          → Divider
  - `![alt](src)` on its own line          → Image(alt, src, emoji=None)
  - `![[emoji:NxM]](src)` on its own line  → Image(alt="", src, emoji=(N,M))
    (alt text is literally `[emoji:NxM]`; the surrounding `![ ]` is just
    the standard MD image syntax)
  - everything else                        → Paragraph(inlines)

Supported inline constructs inside a Paragraph / Heading / list item /
quote / table cell:
  - `*bold*`            → Bold
  - `_italic_`          → Italic
  - `__underline__`     → Underline       (double-underscore)
  - `~strike~`          → Strike
  - `||spoiler||`       → Spoiler
  - `` `code` ``        → Code
  - `[text](url)`       → Link
  - `![alt](src)` inline → InlineImage (only useful as a marker for
    later inline-in-paragraph rendering; usually images sit on own line)

Inline parsing is a tiny tokenizer rather than a regex storm so we get
correct nesting and don't choke on `_foo*bar_baz*`. Escapes via `\\` are
honored.

This intentionally does NOT consume Telegram's wire-level MarkdownV2
escapes (`\\.` `\\(` etc). The user types regular Markdown; we re-escape
on the way out via `bot.md.escape`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


# ---------- inline nodes ----------

@dataclass
class Text:
    value: str

@dataclass
class Bold:
    children: list["Inline"]

@dataclass
class Italic:
    children: list["Inline"]

@dataclass
class Underline:
    children: list["Inline"]

@dataclass
class Strike:
    children: list["Inline"]

@dataclass
class Spoiler:
    children: list["Inline"]

@dataclass
class Code:
    value: str

@dataclass
class Link:
    children: list["Inline"]
    url: str

@dataclass
class InlineImage:
    alt: str
    src: str
    emoji: tuple[int, int] | None = None  # (cols, rows) when ![[emoji:NxM]](…)


Inline = Text | Bold | Italic | Underline | Strike | Spoiler | Code | Link | InlineImage


# ---------- block nodes ----------

@dataclass
class Paragraph:
    inlines: list[Inline]

@dataclass
class Heading:
    level: Literal[1, 2, 3]
    inlines: list[Inline]

@dataclass
class BlockQuote:
    inlines: list[Inline]

@dataclass
class PullQuote:
    inlines: list[Inline]

@dataclass
class CodeBlock:
    lang: str | None
    value: str

@dataclass
class ListBlock:
    ordered: bool
    items: list[list[Inline]] = field(default_factory=list)

@dataclass
class Divider:
    pass

@dataclass
class Image:
    alt: str
    src: str
    emoji: tuple[int, int] | None = None


Block = (
    Paragraph | Heading | BlockQuote | PullQuote | CodeBlock |
    ListBlock | Divider | Image
)


# ---------- public entry ----------

def parse(md: str) -> list[Block]:
    """Parse the full Markdown source into a flat list of blocks."""
    lines = md.splitlines()
    blocks: list[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # blank line → just advance
        if not line.strip():
            i += 1
            continue

        # code fence ```lang
        m = _FENCE_RE.match(line)
        if m:
            lang = m.group(1) or None
            body: list[str] = []
            i += 1
            while i < n and not _FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            if i < n:
                i += 1  # consume closing fence
            blocks.append(CodeBlock(lang=lang, value="\n".join(body)))
            continue

        # divider
        if _DIVIDER_RE.match(line):
            blocks.append(Divider())
            i += 1
            continue

        # heading
        m = _HEADING_RE.match(line)
        if m:
            hashes, text = m.group(1), m.group(2)
            level = min(len(hashes), 3)  # collapse #### + to H3
            blocks.append(Heading(level=level, inlines=_parse_inlines(text)))  # type: ignore[arg-type]
            i += 1
            continue

        # standalone image (incl. emoji marker)
        m = _IMAGE_LINE_RE.match(line.strip())
        if m:
            blocks.append(_image_from_match(m))
            i += 1
            continue

        # pull-quote (must come before block-quote since '>>' starts with '>')
        if line.lstrip().startswith(">>"):
            chunk, i = _consume_prefix(lines, i, prefix=">>")
            blocks.append(PullQuote(inlines=_parse_inlines(chunk)))
            continue

        # block-quote
        if line.lstrip().startswith(">"):
            chunk, i = _consume_prefix(lines, i, prefix=">")
            blocks.append(BlockQuote(inlines=_parse_inlines(chunk)))
            continue

        # list
        if _LIST_ITEM_RE.match(line):
            block, i = _consume_list(lines, i)
            blocks.append(block)
            continue

        # otherwise: paragraph — accumulate until blank / structural line
        para_lines: list[str] = [line]
        i += 1
        while i < n and not _para_terminates(lines[i]):
            para_lines.append(lines[i])
            i += 1
        text = " ".join(s.strip() for s in para_lines)
        blocks.append(Paragraph(inlines=_parse_inlines(text)))

    return blocks


# ---------- block helpers ----------

_FENCE_RE = re.compile(r"^```([A-Za-z0-9_+-]*)\s*$")
_DIVIDER_RE = re.compile(r"^\s*(?:---+|\*\*\*+)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
# Image alt may itself contain one level of brackets to carry the emoji
# marker, e.g. ![[emoji:6x4]](pic.png). Outer `[ ]` are MD image syntax,
# inner `[emoji:NxM]` is our marker.
_IMAGE_LINE_RE = re.compile(
    r"^!\[(?P<alt>\[emoji:\d+x\d+\]|[^\]]*)\]\((?P<src>[^)]+)\)$"
)
_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*]|(\d+)\.)\s+(.*)$")
_EMOJI_ALT_RE = re.compile(r"^\[emoji:(\d+)x(\d+)\]$")


def _para_terminates(line: str) -> bool:
    if not line.strip():
        return True
    if _FENCE_RE.match(line):
        return True
    if _DIVIDER_RE.match(line):
        return True
    if _HEADING_RE.match(line):
        return True
    if _LIST_ITEM_RE.match(line):
        return True
    stripped = line.lstrip()
    if stripped.startswith(">"):
        return True
    if _IMAGE_LINE_RE.match(stripped):
        return True
    return False


def _consume_prefix(lines: list[str], i: int, *, prefix: str) -> tuple[str, int]:
    """Gather consecutive lines starting with `prefix`, return joined inner text."""
    out: list[str] = []
    while i < len(lines):
        ln = lines[i].lstrip()
        if not ln.startswith(prefix):
            break
        out.append(ln[len(prefix):].lstrip())
        i += 1
    return " ".join(out).strip(), i


def _consume_list(lines: list[str], i: int) -> tuple[ListBlock, int]:
    items: list[list[Inline]] = []
    ordered: bool | None = None
    while i < len(lines):
        m = _LIST_ITEM_RE.match(lines[i])
        if not m:
            break
        is_ordered = m.group(2) is not None
        if ordered is None:
            ordered = is_ordered
        elif ordered != is_ordered:
            break  # different list flavor → stop
        items.append(_parse_inlines(m.group(3)))
        i += 1
    return ListBlock(ordered=bool(ordered), items=items), i


def _image_from_match(m: re.Match[str]) -> Image:
    alt = m.group("alt")
    src = m.group("src").strip()
    em = _EMOJI_ALT_RE.match(alt)
    if em:
        return Image(alt="", src=src, emoji=(int(em.group(1)), int(em.group(2))))
    return Image(alt=alt, src=src, emoji=None)


# ---------- inline tokenizer ----------

_INLINE_IMG_RE = re.compile(
    r"!\[(?P<alt>\[emoji:\d+x\d+\]|[^\]]*)\]\((?P<src>[^)]+)\)"
)
_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<url>[^)]+)\)")


def _parse_inlines(text: str) -> list[Inline]:
    """Recursive-descent over emphasis runs."""
    return _Tokenizer(text).parse_until(end=None)


class _Tokenizer:
    """Hand-written walker because regex alternation can't track nesting."""

    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0
        self.n = len(s)

    def parse_until(self, end: str | None) -> list[Inline]:
        out: list[Inline] = []
        buf: list[str] = []

        def flush_text() -> None:
            if buf:
                out.append(Text("".join(buf)))
                buf.clear()

        while self.i < self.n:
            # closing delimiter for current emphasis run
            if end and self._peek(end):
                self.i += len(end)
                flush_text()
                return out

            ch = self.s[self.i]

            # escape: \X → literal X
            if ch == "\\" and self.i + 1 < self.n:
                buf.append(self.s[self.i + 1])
                self.i += 2
                continue

            # inline image / emoji-image — must come before [link]
            if ch == "!" and self.s.startswith("![", self.i):
                m = _INLINE_IMG_RE.match(self.s, self.i)
                if m:
                    flush_text()
                    alt = m.group("alt")
                    src = m.group("src").strip()
                    em = _EMOJI_ALT_RE.match(alt)
                    if em:
                        out.append(InlineImage(
                            alt="", src=src,
                            emoji=(int(em.group(1)), int(em.group(2))),
                        ))
                    else:
                        out.append(InlineImage(alt=alt, src=src, emoji=None))
                    self.i = m.end()
                    continue

            # link
            if ch == "[":
                m = _LINK_RE.match(self.s, self.i)
                if m:
                    flush_text()
                    inner = _parse_inlines(m.group("text"))
                    out.append(Link(children=inner, url=m.group("url").strip()))
                    self.i = m.end()
                    continue

            # inline code
            if ch == "`":
                close = self.s.find("`", self.i + 1)
                if close != -1:
                    flush_text()
                    out.append(Code(value=self.s[self.i + 1:close]))
                    self.i = close + 1
                    continue

            # spoiler ||...||
            if self._peek("||"):
                flush_text()
                self.i += 2
                out.append(Spoiler(children=self.parse_until("||")))
                continue

            # underline __...__
            if self._peek("__"):
                flush_text()
                self.i += 2
                out.append(Underline(children=self.parse_until("__")))
                continue

            # strike ~...~
            if ch == "~":
                flush_text()
                self.i += 1
                out.append(Strike(children=self.parse_until("~")))
                continue

            # bold *...*
            if ch == "*":
                flush_text()
                self.i += 1
                out.append(Bold(children=self.parse_until("*")))
                continue

            # italic _..._  (single underscore, after we already checked __ )
            if ch == "_":
                flush_text()
                self.i += 1
                out.append(Italic(children=self.parse_until("_")))
                continue

            buf.append(ch)
            self.i += 1

        flush_text()
        return out

    def _peek(self, s: str) -> bool:
        return self.s.startswith(s, self.i)
