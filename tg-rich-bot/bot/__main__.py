"""Bot entrypoint.

Step 3: wires up the compose handler. /ping still works as a smoke test;
any other text message is treated as MarkdownV2 to render as a preview.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from .api import BotAPI
from .config import get_settings
from .emoji.pack import EmojiPackManager, MosaicCache
from .handlers.compose import ComposeHandler
from .handlers.drafts import DraftStore
from .handlers.publish import PublishHandler
from .poller import Poller

try:
    import uvloop  # type: ignore
except ImportError:  # pragma: no cover
    uvloop = None


async def _amain() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("bot")

    api = BotAPI(settings.bot_token, base=settings.api_base)
    me = await api.call("getMe")
    log.info("logged in as @%s (id=%s)", me.get("username"), me.get("id"))

    poller = Poller(api, owner_id=settings.owner_id)

    async def ping(upd: dict[str, Any]) -> None:
        msg = upd.get("message")
        if not msg or "text" not in msg:
            return
        if msg["text"].startswith("/ping"):
            await api.call("sendMessage", {
                "chat_id": msg["chat"]["id"],
                "text": "🏓 понг",
                "reply_parameters": {"message_id": msg["message_id"]},
            })

    compose = ComposeHandler(api, DraftStore())
    if settings.owner_id and me.get("username"):
        from pathlib import Path
        cache = MosaicCache(Path(".claude") / "mosaic_cache.json")
        compose.emoji_packs = EmojiPackManager(
            api, owner_id=settings.owner_id,
            bot_username=me["username"], cache=cache,
        )
    publish = PublishHandler(api, compose.drafts, settings)

    async def compose_dispatch(upd: dict[str, Any]) -> None:
        msg = upd.get("message")
        if not msg:
            return
        # only handle messages that could carry MD content or media
        if not any(k in msg for k in ("text", "caption", "photo", "document", "media_group_id")):
            return
        if (msg.get("text") or "").startswith("/ping"):
            return  # handled by ping()
        await compose.handle(upd)

    async def publish_dispatch(upd: dict[str, Any]) -> None:
        if "callback_query" in upd:
            await publish.handle(upd)

    poller.on_update(ping)
    poller.on_update(compose_dispatch)
    poller.on_update(publish_dispatch)

    try:
        await poller.run()
    finally:
        await compose.aclose()
        await api.aclose()


def main() -> None:
    if uvloop is not None:
        uvloop.install()
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
