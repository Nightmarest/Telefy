"""Album collector — groups inbound media_group messages into one logical post.

Telegram delivers album messages as separate `message` updates that share
`media_group_id`. Caption is on the *first* message only. We buffer
incoming pieces for a short window, then fire a single callback.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

AlbumHandler = Callable[[list[dict[str, Any]]], Awaitable[None]]


class AlbumCollector:
    """Buffers messages by media_group_id; flushes after `flush_after` seconds."""

    def __init__(self, on_album: AlbumHandler, *, flush_after: float = 1.2) -> None:
        self._on_album = on_album
        self._flush_after = flush_after
        self._buf: dict[str, list[dict[str, Any]]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def offer(self, msg: dict[str, Any]) -> bool:
        """Return True if this message belongs to an album we're buffering."""
        gid = msg.get("media_group_id")
        if not gid:
            return False
        self._buf.setdefault(gid, []).append(msg)
        # restart the flush timer on every new piece
        if gid in self._tasks:
            self._tasks[gid].cancel()
        self._tasks[gid] = asyncio.create_task(self._flush_later(gid))
        return True

    async def _flush_later(self, gid: str) -> None:
        try:
            await asyncio.sleep(self._flush_after)
        except asyncio.CancelledError:
            return
        msgs = self._buf.pop(gid, [])
        self._tasks.pop(gid, None)
        if not msgs:
            return
        # preserve send order
        msgs.sort(key=lambda m: m.get("message_id", 0))
        try:
            await self._on_album(msgs)
        except Exception:
            log.exception("album handler crashed (gid=%s)", gid)
