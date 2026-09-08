from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageOps


_BODY_SPECIALS = set("_*[]()~`>#+-=|{}.!")
FALLBACK_EMOJI = "⬜"
TILE_PX = 100
MAX_MOSAIC_DIM = 10


class TelegramAPIError(RuntimeError):
    def __init__(self, method: str, code: int, description: str, parameters: dict | None = None):
        super().__init__(f"{method} -> {code}: {description}")
        self.method = method
        self.code = code
        self.description = description
        self.parameters = parameters or {}


def escape_text(s: str) -> str:
    out = []
    for ch in s:
        if ch in _BODY_SPECIALS:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def escape_code(s: str) -> str:
    return s.replace("\\", "\\\\").replace("`", "\\`")


def escape_link_url(url: str) -> str:
    return url.replace("\\", "\\\\").replace(")", "\\)")


class TelegramRichClient:
    def __init__(self, token: str, base: str = "https://api.telegram.org") -> None:
        self.token = token
        self.base = base.rstrip("/")
        self.url = f"{self.base}/bot{token}"
        self.file_url = f"{self.base}/file/bot{token}"
        self.session = requests.Session()
        self._custom_emoji_cache: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        self.session.close()

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> Any:
        url = f"{self.url}/{method}"
        if files:
            data = {k: _to_form(v) for k, v in (params or {}).items()}
            resp = self.session.post(url, data=data, files=files, timeout=timeout)
        else:
            resp = self.session.post(url, json=params or {}, timeout=timeout)
        try:
            payload = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise
        if payload.get("ok"):
            return payload.get("result")
        raise TelegramAPIError(
            method,
            payload.get("error_code", resp.status_code),
            payload.get("description", "unknown error"),
            payload.get("parameters") or {},
        )

    def send_message(self, chat_id: str | int, text: str, *, reply_to: int | None = None) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to is not None:
            params["reply_parameters"] = {"message_id": reply_to}
        return self.call("sendMessage", params)

    def send_photo(
        self,
        chat_id: str | int,
        photo: str | bytes,
        caption: str | None = None,
        *,
        caption_entities: list[dict[str, Any]] | None = None,
        parse_mode: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            params["caption"] = caption
        if caption_entities is not None:
            params["caption_entities"] = caption_entities
        if parse_mode is not None:
            params["parse_mode"] = parse_mode
        if isinstance(photo, bytes):
            payload = {"chat_id": chat_id}
            if caption is not None:
                payload["caption"] = caption
            if caption_entities is not None:
                payload["caption_entities"] = caption_entities
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            return self.call(
                "sendPhoto",
                payload,
                files={"photo": ("card.jpg", photo, "image/jpeg")},
            )
        return self.call("sendPhoto", params)

    def send_rich_message(self, chat_id: str | int, markdown: str) -> Any:
        return self.call("sendRichMessage", {
            "chat_id": chat_id,
            "rich_message": {"markdown": markdown},
        })

    def copy_message(
        self,
        chat_id: str | int,
        from_chat_id: str | int,
        message_id: int,
    ) -> Any:
        return self.call("copyMessage", {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": []},
        })

    def edit_rich_message(self, chat_id: str | int, message_id: int, markdown: str) -> Any:
        return self.call("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "rich_message": {"markdown": markdown},
        })

    def edit_photo_caption(
        self,
        chat_id: str | int,
        message_id: int,
        caption: str,
        *,
        caption_entities: list[dict[str, Any]] | None = None,
        parse_mode: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
        }
        if caption_entities is not None:
            params["caption_entities"] = caption_entities
        if parse_mode is not None:
            params["parse_mode"] = parse_mode
        return self.call("editMessageCaption", params)

    def edit_photo(
        self,
        chat_id: str | int,
        message_id: int,
        photo: bytes,
        caption: str | None = None,
        *,
        caption_entities: list[dict[str, Any]] | None = None,
        parse_mode: str | None = None,
    ) -> Any:
        media: dict[str, Any] = {
            "type": "photo",
            "media": "attach://photo",
        }
        if caption is not None:
            media["caption"] = caption
        if caption_entities is not None:
            media["caption_entities"] = caption_entities
        if parse_mode is not None:
            media["parse_mode"] = parse_mode
        return self.call(
            "editMessageMedia",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "media": media,
            },
            files={"photo": ("card.jpg", photo, "image/jpeg")},
        )

    def delete_message(self, chat_id: str | int, message_id: int) -> Any:
        return self.call("deleteMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
        })

    def download(self, url: str, *, timeout: float = 30.0) -> bytes:
        resp = self.session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.content

    def get_custom_emoji_stickers(self, custom_emoji_ids: list[str]) -> list[dict[str, Any]]:
        missing = [emoji_id for emoji_id in custom_emoji_ids if emoji_id not in self._custom_emoji_cache]
        if missing:
            stickers = self.call("getCustomEmojiStickers", {
                "custom_emoji_ids": missing,
            })
            for sticker in stickers:
                emoji_id = sticker.get("custom_emoji_id")
                if emoji_id:
                    self._custom_emoji_cache[emoji_id] = sticker
        return [
            self._custom_emoji_cache[emoji_id]
            for emoji_id in custom_emoji_ids
            if emoji_id in self._custom_emoji_cache
        ]


def build_progress_bar(progress_ms: int, duration_ms: int, width: int = 10) -> str:
    if duration_ms <= 0:
        return "▱" * width
    ratio = max(0.0, min(progress_ms / duration_ms, 1.0))
    filled = round(ratio * width)
    return "▰" * filled + "▱" * (width - filled)


def format_time(ms: int) -> str:
    total = max(0, ms // 1000)
    return f"{total // 60}:{total % 60:02d}"


def build_spotify_markdown(
    *,
    cover_url: str,
    track_name: str,
    artists: list[dict[str, str]],
    progress_ms: int,
    duration_ms: int,
    artist_stack_markdown: str | None = None,
) -> str:
    artist_line_parts = []
    for a in artists:
        name = escape_text(a["name"])
        url = a.get("url") or ""
        if url:
            artist_line_parts.append(f"[{name}]({escape_link_url(url)})")
        else:
            artist_line_parts.append(name)
    artist_line = " · ".join(artist_line_parts)
    parts = [
        f"![cover]({escape_link_url(cover_url)})",
        "",
        f"*{escape_text(track_name)}*",
        artist_line,
    ]
    if artist_stack_markdown:
        parts.extend(["", artist_stack_markdown])
    parts.extend([
        "",
        f"`{escape_code(format_time(progress_ms))}` / `{escape_code(format_time(duration_ms))}`  {build_progress_bar(progress_ms, duration_ms)}",
    ])
    return "\n".join(parts)


@dataclass
class MosaicCache:
    path: Path

    def __post_init__(self) -> None:
        self._data: dict[str, list[str]] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def get(self, sig: str) -> list[str] | None:
        return self._data.get(sig)

    def put(self, sig: str, ids: list[str]) -> None:
        self._data[sig] = ids
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data))
        os.replace(tmp, self.path)


@dataclass
class MosaicTile:
    row: int
    col: int
    png: bytes


def mosaic_signature(image_bytes: bytes, cols: int, rows: int) -> str:
    h = hashlib.sha256()
    h.update(b"telefy-mosaic-v2")
    h.update(cols.to_bytes(4, "big"))
    h.update(rows.to_bytes(4, "big"))
    h.update(image_bytes)
    return h.hexdigest()


def slice_mosaic(image_bytes: bytes, cols: int, rows: int) -> list[MosaicTile]:
    if cols < 1 or rows < 1:
        raise ValueError(f"mosaic dims must be >= 1, got {cols}x{rows}")
    if cols > MAX_MOSAIC_DIM or rows > MAX_MOSAIC_DIM:
        raise ValueError(
            f"mosaic dims capped at {MAX_MOSAIC_DIM}x{MAX_MOSAIC_DIM}, got {cols}x{rows}"
        )

    with Image.open(BytesIO(image_bytes)) as img:
        image = img.convert("RGBA")
        target_w = cols * TILE_PX
        target_h = rows * TILE_PX
        canvas = ImageOps.fit(
            image,
            (target_w, target_h),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    tiles: list[MosaicTile] = []
    for row in range(rows):
        for col in range(cols):
            box = (
                col * TILE_PX,
                row * TILE_PX,
                (col + 1) * TILE_PX,
                (row + 1) * TILE_PX,
            )
            tile = canvas.crop(box)
            buf = BytesIO()
            tile.save(buf, format="PNG", optimize=True)
            tiles.append(MosaicTile(row=row, col=col, png=buf.getvalue()))
    return tiles


def _input_sticker(file_id: str) -> dict[str, Any]:
    return {
        "sticker": file_id,
        "format": "static",
        "emoji_list": [FALLBACK_EMOJI],
    }


def _new_pack_name(bot_username: str) -> str:
    return f"m_{secrets.token_hex(8)}_by_{re.sub(r'[^A-Za-z0-9_]', '', bot_username)}"


def _is_invalid_sticker_set(error: TelegramAPIError) -> bool:
    description = error.description or ""
    return "STICKERSET_INVALID" in description or "not found" in description.lower()


class EmojiPackManager:
    def __init__(
        self,
        api: TelegramRichClient,
        owner_id: int,
        bot_username: str,
        cache: MosaicCache,
    ) -> None:
        self.api = api
        self.owner_id = owner_id
        self.cache = cache
        self.bot_username = bot_username

    def emoji_ids_for_mosaic(self, image_bytes: bytes, cols: int, rows: int) -> list[str]:
        sig = mosaic_signature(image_bytes, cols, rows)
        cached = self.cache.get(sig)
        if cached:
            return cached
        tiles = slice_mosaic(image_bytes, cols, rows)
        uploaded_file_ids: list[str] = []
        for tile in tiles:
            sticker_obj = self.api.call(
                "uploadStickerFile",
                {
                    "user_id": self.owner_id,
                    "sticker_format": "static",
                },
                files={"sticker": (f"tile_{tile.row}_{tile.col}.png", tile.png, "image/png")},
            )
            uploaded_file_ids.append(sticker_obj["file_id"])

        pack_name = _new_pack_name(self.bot_username)
        initial = uploaded_file_ids[:50]
        self.api.call(
            "createNewStickerSet",
            {
                "user_id": self.owner_id,
                "name": pack_name,
                "title": "Telefy Mosaic",
                "sticker_type": "custom_emoji",
                "stickers": [_input_sticker(fid) for fid in initial],
            },
        )
        self._wait_for_pack(pack_name)

        for fid in uploaded_file_ids[len(initial):]:
            self._add_sticker_with_retry(pack_name, fid)

        pack = self.api.call("getStickerSet", {"name": pack_name})
        emoji_ids = [s["custom_emoji_id"] for s in pack.get("stickers", [])]
        if len(emoji_ids) < len(tiles):
            raise RuntimeError(
                f"emoji pack returned too few tiles: {len(emoji_ids)} < {len(tiles)}"
            )
        ids = emoji_ids[:len(tiles)]
        self.cache.put(sig, ids)
        return ids

    def _wait_for_pack(self, pack_name: str) -> None:
        for attempt in range(6):
            try:
                self.api.call("getStickerSet", {"name": pack_name})
                return
            except TelegramAPIError as e:
                if not _is_invalid_sticker_set(e) or attempt == 5:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def _add_sticker_with_retry(self, pack_name: str, file_id: str) -> None:
        for attempt in range(6):
            try:
                self.api.call("addStickerToSet", {
                    "user_id": self.owner_id,
                    "name": pack_name,
                    "sticker": _input_sticker(file_id),
                })
                return
            except TelegramAPIError as e:
                if not _is_invalid_sticker_set(e) or attempt == 5:
                    raise
                time.sleep(0.5 * (attempt + 1))


def compose_artist_stack(image_urls: list[str], downloader: TelegramRichClient) -> bytes | None:
    if not image_urls:
        return None

    canvas_size = 300
    avatar_size = 220
    step = 90
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    group_width = avatar_size + max(0, len(image_urls) - 1) * step
    start_x = max(0, (canvas_size - group_width) // 2)
    start_y = max(0, (canvas_size - avatar_size) // 2)

    for i, url in enumerate(image_urls):
        try:
            raw = downloader.download(url)
            with Image.open(BytesIO(raw)) as src:
                avatar = src.convert("RGBA").resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        except Exception:
            continue

        mask = Image.new("L", (avatar_size, avatar_size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)

        circular = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
        circular.paste(avatar, (0, 0), mask)

        x = start_x + i * step
        y = start_y
        canvas.alpha_composite(circular, (x, y))

        # soft ring so overlapped avatars still read cleanly
        ring = Image.new("RGBA", (avatar_size, avatar_size), (0, 0, 0, 0))
        ring_draw = ImageDraw.Draw(ring)
        ring_draw.ellipse((2, 2, avatar_size - 3, avatar_size - 3), outline=(255, 255, 255, 220), width=8)
        canvas.alpha_composite(ring, (x, y))

    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def artist_stack_markdown(
    artists: list[dict[str, str]],
    downloader: TelegramRichClient,
    emoji_manager: EmojiPackManager | None,
) -> str | None:
    if not artists or emoji_manager is None:
        return None
    image_bytes = compose_artist_stack([a["image"] for a in artists], downloader)
    if image_bytes is None:
        return None
    ids = emoji_manager.emoji_ids_for_mosaic(image_bytes, 3, 3)
    lines: list[str] = []
    for row in range(3):
        offset = row * 3
        line = "".join(f"![{FALLBACK_EMOJI}](tg://emoji?id={emoji_id})" for emoji_id in ids[offset:offset + 3])
        lines.append(line)
    return "<br>\n".join(lines)


def artist_stack_ids(
    artists: list[dict[str, str]],
    downloader: TelegramRichClient,
    emoji_manager: EmojiPackManager | None,
    *,
    cols: int = 3,
    rows: int = 3,
) -> list[str] | None:
    if not artists or emoji_manager is None:
        return None
    image_bytes = compose_artist_stack([a["image"] for a in artists], downloader)
    if image_bytes is None:
        return None
    return emoji_manager.emoji_ids_for_mosaic(image_bytes, cols, rows)


def _to_form(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
