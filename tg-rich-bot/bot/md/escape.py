"""MarkdownV2 escape utilities.

Reference: https://core.telegram.org/bots/api#markdownv2-style
Characters that must be escaped in plain text:
    _ * [ ] ( ) ~ ` > # + - = | { } . !

Inside code/pre: only ` and \\ must be escaped.
Inside (link) URLs: ) and \\ must be escaped.
"""
from __future__ import annotations

_BODY_SPECIALS = set("_*[]()~`>#+-=|{}.!")


def escape_text(s: str) -> str:
    """Escape MarkdownV2 specials in regular message text."""
    out = []
    for ch in s:
        if ch in _BODY_SPECIALS:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def escape_code(s: str) -> str:
    """Escape for inside ` ` / ``` ``` blocks."""
    return s.replace("\\", "\\\\").replace("`", "\\`")


def escape_link_url(url: str) -> str:
    """Escape for inside (…) of [text](url)."""
    return url.replace("\\", "\\\\").replace(")", "\\)")
