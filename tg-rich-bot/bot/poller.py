"""Long-polling loop. Dispatches updates to the relevant handler."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from .api import BotAPI, BotAPIError, BotAPINetworkError

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class Poller:
    def __init__(self, api: BotAPI, owner_id: int) -> None:
        self.api = api
        self.owner_id = owner_id
        self._offset: int | None = None
        self._handlers: list[Handler] = []

    def on_update(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def run(self) -> None:
        log.info("poller starting (owner=%d)", self.owner_id)
        while True:
            try:
                updates = await self.api.call(
                    "getUpdates",
                    {"timeout": 50, "offset": self._offset, "allowed_updates": [
                        "message", "edited_message", "callback_query",
                    ]},
                )
            except (BotAPIError, BotAPINetworkError) as e:
                log.error("getUpdates failed: %s", e)
                await asyncio.sleep(3)
                continue

            for upd in updates or []:
                self._offset = upd["update_id"] + 1
                if not self._owned(upd):
                    continue
                for h in self._handlers:
                    try:
                        await h(upd)
                    except Exception:
                        log.exception("handler crashed on update %s", upd.get("update_id"))

    def _owned(self, upd: dict[str, Any]) -> bool:
        for key in ("message", "edited_message", "callback_query"):
            obj = upd.get(key)
            if obj and (obj.get("from") or {}).get("id") == self.owner_id:
                return True
        return False
