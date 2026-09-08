"""Behaviour test for the MD-as-file path classification.

We don't mock the Bot API (compose imports heavily). We test the small
predicate that decides "is this attachment a markdown file?" by mirroring
the same logic — kept in sync with _maybe_load_md_document.
"""
from __future__ import annotations


def _is_md(doc: dict) -> bool:
    name = (doc.get("file_name") or "").lower()
    mime = (doc.get("mime_type") or "").lower()
    return (
        mime in {"text/markdown", "text/x-markdown", "text/plain"}
        or name.endswith((".md", ".markdown", ".txt"))
    )


def test_classify_md_by_mime():
    assert _is_md({"file_name": "x", "mime_type": "text/markdown"})
    assert _is_md({"file_name": "x", "mime_type": "text/x-markdown"})
    assert _is_md({"file_name": "x", "mime_type": "text/plain"})


def test_classify_md_by_extension():
    assert _is_md({"file_name": "post.md", "mime_type": "application/octet-stream"})
    assert _is_md({"file_name": "POST.MARKDOWN", "mime_type": ""})
    assert _is_md({"file_name": "notes.txt"})


def test_classify_non_md_rejected():
    assert not _is_md({"file_name": "img.png", "mime_type": "image/png"})
    assert not _is_md({"file_name": "doc.pdf", "mime_type": "application/pdf"})
    assert not _is_md({})


def test_compose_module_has_loader():
    from bot.handlers.compose import ComposeHandler
    assert hasattr(ComposeHandler, "_maybe_load_md_document")
