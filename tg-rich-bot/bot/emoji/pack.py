"""Upload mosaic tiles into a custom-emoji sticker set, return emoji IDs.

Telegram model:
  1. uploadStickerFile(user_id, sticker, sticker_format='static') → file_id
  2. createNewStickerSet(user_id, name, title, stickers=[...],
        sticker_type='custom_emoji')
  3. addStickerToSet for tiles beyond the 50-item creation limit
  3. getStickerSet(name) → set.stickers[*].custom_emoji_id

Every rendered mosaic gets a new sticker set. This prevents the shared
pack from eventually failing with STICKERS_TOO_MUCH.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any

from ..api import BotAPI, BotAPIError
from .slicer import MosaicTile, slice_mosaic, mosaic_signature

log = logging.getLogger(__name__)


# A custom_emoji is referenced by a one-char emoji that Telegram clients
# use as a fallback if the custom rendering isn't available. We use a
# white square — it's neutral and visible on all themes.
FALLBACK_EMOJI = "⬜"


class MosaicCache:
    """Persistent cache: signature → list[custom_emoji_id]."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, list[str]] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                log.warning("could not load mosaic cache at %s; starting fresh", path)
                self._data = {}

    def get(self, sig: str) -> list[str] | None:
        return self._data.get(sig)

    def put(self, sig: str, ids: list[str]) -> None:
        self._data[sig] = ids
        self._flush()

    def _flush(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data))
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("failed to persist mosaic cache: %s", e)


class EmojiPackManager:
    """Wraps the sticker-set lifecycle for one bot+owner."""

    def __init__(
        self,
        api: BotAPI,
        owner_id: int,
        bot_username: str,
        cache: MosaicCache,
    ) -> None:
        self.api = api
        self.owner_id = owner_id
        self.cache = cache
        # Sticker-set names must match [A-Za-z0-9_]+, end with _by_<botname>.
        self.bot_username = re.sub(r"[^A-Za-z0-9_]", "", bot_username)
        self._pack_lock = asyncio.Lock()

    async def emoji_ids_for_mosaic(
        self, image_bytes: bytes, cols: int, rows: int,
    ) -> list[str]:
        """Top-level entry: returns custom_emoji_ids in row-major order.

        A fresh custom-emoji sticker set is created for every call.
        """
        sig = mosaic_signature(image_bytes, cols, rows)
        log.info("creating mosaic %s in a fresh pack (%dx%d)", sig, cols, rows)
        tiles = slice_mosaic(image_bytes, cols, rows)

        # Serialize pack creation and uploads to avoid Telegram rate races.
        async with self._pack_lock:
            return await self._create_pack_and_get_ids(tiles)

    # ---------- lower-level steps ----------

    async def _create_pack_and_get_ids(self, tiles: list[MosaicTile]) -> list[str]:
        # 1. Upload each tile PNG separately to get a file_id.
        uploaded_file_ids: list[str] = []
        for tile in tiles:
            sticker_obj = await self.api.call(
                "uploadStickerFile",
                {
                    "user_id": self.owner_id,
                    "sticker_format": "static",
                },
                files={"sticker": (f"tile_{tile.row}_{tile.col}.png",
                                   tile.png, "image/png")},
            )
            uploaded_file_ids.append(sticker_obj["file_id"])

        pack_name = self._new_pack_name()
        initial = uploaded_file_ids[:50]
        await self.api.call(
            "createNewStickerSet",
            {
                "user_id": self.owner_id,
                "name": pack_name,
                "title": "Mosaic",
                "sticker_type": "custom_emoji",
                "stickers": [_input_sticker(fid) for fid in initial],
            },
        )
        await self._wait_for_pack(pack_name)

        # createNewStickerSet accepts at most 50 initial stickers.
        for fid in uploaded_file_ids[len(initial):]:
            await self._add_sticker_with_retry(pack_name, fid)

        pack = await self.api.call("getStickerSet", {"name": pack_name})
        emoji_ids = [s["custom_emoji_id"] for s in pack.get("stickers", [])]

        if len(emoji_ids) < len(tiles):
            raise RuntimeError(
                "набор эмодзи содержит меньше новых плиток, чем ожидалось: "
                f"{len(emoji_ids)} < {len(tiles)}"
            )
        return emoji_ids[:len(tiles)]

    def _new_pack_name(self) -> str:
        return f"m_{secrets.token_hex(8)}_by_{self.bot_username}"

    async def _wait_for_pack(self, pack_name: str) -> None:
        for attempt in range(6):
            try:
                await self.api.call("getStickerSet", {"name": pack_name})
                return
            except BotAPIError as e:
                if not _is_invalid_sticker_set(e) or attempt == 5:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

    async def _add_sticker_with_retry(
        self,
        pack_name: str,
        file_id: str,
    ) -> None:
        for attempt in range(6):
            try:
                await self.api.call("addStickerToSet", {
                    "user_id": self.owner_id,
                    "name": pack_name,
                    "sticker": _input_sticker(file_id),
                })
                return
            except BotAPIError as e:
                if not _is_invalid_sticker_set(e) or attempt == 5:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))


def _input_sticker(file_id: str) -> dict[str, Any]:
    return {
        "sticker": file_id,
        "format": "static",
        "emoji_list": [FALLBACK_EMOJI],
    }


def _is_invalid_sticker_set(error: BotAPIError) -> bool:
    description = error.description or ""
    return (
        "STICKERSET_INVALID" in description
        or "not found" in description.lower()
    )
