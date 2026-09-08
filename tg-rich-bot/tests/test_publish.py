import time
from types import SimpleNamespace

import pytest

from bot.handlers.drafts import DraftStore
from bot.handlers.publish import PublishHandler, _message_link, build_keyboard


# ---------- DraftStore ----------

def test_draft_create_and_get():
    s = DraftStore()
    d = s.create(user_id=42, payload={"blocks": []}, preview_chat_id=42, preview_message_id=7)
    assert d.token
    assert s.get(d.token) is d
    assert s.get(d.token).payload == {"blocks": []}


def test_draft_drop_removes():
    s = DraftStore()
    d = s.create(user_id=1, payload={}, preview_chat_id=1, preview_message_id=1)
    assert s.drop(d.token) is d
    assert s.get(d.token) is None
    assert s.drop(d.token) is None  # idempotent


def test_draft_unknown_token():
    s = DraftStore()
    assert s.get("nope") is None


def test_draft_token_fits_callback_data():
    # Telegram cap is 64 bytes total. We prefix "pub:" / "redo:" / "drop:".
    s = DraftStore()
    d = s.create(user_id=1, payload={}, preview_chat_id=1, preview_message_id=1)
    for prefix in ("pub:", "redo:", "drop:"):
        assert len((prefix + d.token).encode("utf-8")) <= 64


def test_draft_tokens_are_unique():
    s = DraftStore()
    tokens = {
        s.create(user_id=1, payload={}, preview_chat_id=1, preview_message_id=i).token
        for i in range(100)
    }
    assert len(tokens) == 100


def test_draft_expires_after_ttl(monkeypatch):
    s = DraftStore(ttl=0.05)
    d = s.create(user_id=1, payload={}, preview_chat_id=1, preview_message_id=1)
    assert s.get(d.token) is d
    time.sleep(0.1)
    assert s.get(d.token) is None


# ---------- keyboard ----------

def test_build_keyboard_shape():
    kb = build_keyboard("abc123")
    [row] = kb["inline_keyboard"]
    assert [b["text"] for b in row] == ["✅ Опубликовать", "✏️ Заново", "🗑 Отмена"]
    assert [b["callback_data"] for b in row] == ["pub:abc123", "redo:abc123", "drop:abc123"]


# ---------- _message_link ----------

def test_message_link_for_public_channel():
    sent = {"message_id": 17}
    assert _message_link(sent, "@my_channel") == "https://t.me/my_channel/17"


def test_message_link_for_private_channel():
    sent = {"message_id": 9}
    assert _message_link(sent, "-1001234567890") == "https://t.me/c/1234567890/9"


def test_message_link_unknown_format_is_none():
    assert _message_link({"message_id": 1}, "weird") is None


def test_message_link_no_message_id():
    assert _message_link({}, "@x") is None


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def call(self, method, params):
        self.calls.append((method, params))
        if method == "copyMessage":
            return {"message_id": 99}
        return True


async def test_publish_copies_rendered_preview_to_preserve_custom_emoji():
    api = FakeAPI()
    drafts = DraftStore()
    draft = drafts.create(
        user_id=1,
        payload={"markdown": "![⬜](tg://emoji?id=123)"},
        preview_chat_id=42,
        preview_message_id=7,
    )
    handler = PublishHandler(
        api,  # type: ignore[arg-type]
        drafts,
        SimpleNamespace(channel_id="@channel"),  # type: ignore[arg-type]
    )

    await handler._publish("callback", draft)

    method, params = api.calls[0]
    assert method == "copyMessage"
    assert params == {
        "chat_id": "@channel",
        "from_chat_id": 42,
        "message_id": 7,
        "reply_markup": {"inline_keyboard": []},
    }
