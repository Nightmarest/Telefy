"""Publish handler — answers the inline buttons under preview messages.

Three actions encoded in `callback_data`:
  pub:<token>   → forward the draft's payload to CHANNEL_ID
  redo:<token>  → drop the draft, leave preview, ask user to resend MD
  drop:<token>  → drop the draft and delete the preview message
"""
from __future__ import annotations

import logging
from typing import Any

from ..api import BotAPI, BotAPIError, BotAPINetworkError
from ..config import Settings
from .drafts import DraftStore

log = logging.getLogger(__name__)


PUBLISH_OK = "✅ Опубликовано!"
PUBLISH_FAIL = "⚠️ Telegram не принял пост"
DRAFT_GONE = "⏳ Черновик устарел или уже использован. Пришли новое сообщение."


def build_keyboard(token: str) -> dict[str, Any]:
    """Three-button inline keyboard for a freshly rendered preview."""
    return {
        "inline_keyboard": [[
            {"text": "✅ Опубликовать", "callback_data": f"pub:{token}"},
            {"text": "✏️ Заново",       "callback_data": f"redo:{token}"},
            {"text": "🗑 Отмена",       "callback_data": f"drop:{token}"},
        ]],
    }


class PublishHandler:
    def __init__(self, api: BotAPI, drafts: DraftStore, settings: Settings) -> None:
        self.api = api
        self.drafts = drafts
        self.channel_id = settings.channel_id

    async def handle(self, upd: dict[str, Any]) -> None:
        cq = upd.get("callback_query")
        if not cq:
            return
        data: str = cq.get("data") or ""
        if ":" not in data:
            return
        action, token = data.split(":", 1)
        if action not in {"pub", "redo", "drop"}:
            return

        cq_id = cq["id"]
        draft = self.drafts.get(token)
        if draft is None:
            await self.api.call("answerCallbackQuery", {
                "callback_query_id": cq_id,
                "text": DRAFT_GONE,
                "show_alert": True,
            })
            # also clear the dead buttons
            msg = cq.get("message") or {}
            if msg:
                await self._strip_buttons(msg["chat"]["id"], msg["message_id"])
            return

        if action == "pub":
            await self._publish(cq_id, draft)
        elif action == "redo":
            await self._redo(cq_id, draft)
        elif action == "drop":
            await self._drop(cq_id, draft)

    # ---------- actions ----------

    async def _publish(self, cq_id: str, draft: Any) -> None:
        try:
            # Copy the already-rendered preview instead of asking Telegram to
            # parse the Rich Markdown again in the channel context. This keeps
            # custom emoji entities intact.
            sent = await self.api.call("copyMessage", {
                "chat_id": self.channel_id,
                "from_chat_id": draft.preview_chat_id,
                "message_id": draft.preview_message_id,
                "reply_markup": {"inline_keyboard": []},
            })
        except (BotAPIError, BotAPINetworkError) as e:
            log.exception("publish failed")
            detail = (
                f"{e.code} {e.description[:120]}"
                if isinstance(e, BotAPIError)
                else str(e)[:120]
            )
            await self.api.call("answerCallbackQuery", {
                "callback_query_id": cq_id,
                "text": f"{PUBLISH_FAIL}: {detail}",
                "show_alert": True,
            })
            return

        link = _message_link(sent, self.channel_id)
        await self.api.call("answerCallbackQuery", {
            "callback_query_id": cq_id,
            "text": PUBLISH_OK,
        })
        # neutralize the buttons + add a "go to post" link if we have one
        kb: dict[str, Any] = {"inline_keyboard": [[
            {"text": "✓ Опубликовано", "callback_data": "noop"},
        ]]}
        if link:
            kb["inline_keyboard"][0].append({"text": "↗ Открыть пост", "url": link})
        await self.api.call("editMessageReplyMarkup", {
            "chat_id": draft.preview_chat_id,
            "message_id": draft.preview_message_id,
            "reply_markup": kb,
        })
        self.drafts.drop(draft.token)

    async def _redo(self, cq_id: str, draft: Any) -> None:
        self.drafts.drop(draft.token)
        await self.api.call("answerCallbackQuery", {
            "callback_query_id": cq_id,
            "text": "✏️ Пришли новую версию сообщения.",
        })
        await self._strip_buttons(draft.preview_chat_id, draft.preview_message_id)

    async def _drop(self, cq_id: str, draft: Any) -> None:
        self.drafts.drop(draft.token)
        await self.api.call("answerCallbackQuery", {
            "callback_query_id": cq_id,
            "text": "🗑 Удалено.",
        })
        try:
            await self.api.call("deleteMessage", {
                "chat_id": draft.preview_chat_id,
                "message_id": draft.preview_message_id,
            })
        except BotAPIError as e:
            log.warning("could not delete preview: %s", e)

    async def _strip_buttons(self, chat_id: int, message_id: int) -> None:
        try:
            await self.api.call("editMessageReplyMarkup", {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            })
        except BotAPIError as e:
            log.debug("editMessageReplyMarkup ignored: %s", e)


def _message_link(sent: dict[str, Any], channel: str) -> str | None:
    """Build a t.me link to the published post if possible."""
    mid = sent.get("message_id")
    if not mid:
        return None
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}/{mid}"
    # numeric -100… → strip the -100 prefix and use /c/<id>/<msg>
    if channel.startswith("-100"):
        return f"https://t.me/c/{channel[4:]}/{mid}"
    return None
