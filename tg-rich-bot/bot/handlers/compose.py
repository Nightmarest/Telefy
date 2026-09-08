"""Receive rich-message Markdown and render a preview."""
from __future__ import annotations

import logging
import re
from typing import Any

from ..api import BotAPI, BotAPIError, BotAPINetworkError
from ..emoji.pack import EmojiPackManager, FALLBACK_EMOJI
from ..util.album import AlbumCollector
from .drafts import DraftStore
from .image_source import ImageResolutionError, ImageResolver
from .publish import build_keyboard

log = logging.getLogger(__name__)

_EMOJI_URL_RE = re.compile(
    r"!\[\[emoji:(?P<cols>\d+)x(?P<rows>\d+)\]\]"
    r"\((?P<url>https?://[^)\s]+)\)",
    re.IGNORECASE,
)

WELCOME = (
    "👋 Привет! Я превращаю Markdown в красивые посты для канала.\n\n"
    "📝 Что можно прислать:\n"
    "  • текстовое сообщение с разметкой\n"
    "  • фото или альбом с подписью\n"
    "  • файл .md / .markdown / .txt\n\n"
    "🖼 Картинки в разметке:\n"
    "  ![alt](https://…/a.png)    — по публичной HTTPS-ссылке\n\n"
    "✨ Мозаика из custom emoji:\n"
    "  ![[emoji:5x3]](https://…/logo.png)\n"
    "  | *Имя*\n"
    "  | Должность\n"
    "  | Компания\n\n"
    "После рендера покажу превью и кнопки публикации."
)


class ComposeHandler:
    def __init__(
        self, api: BotAPI, drafts: DraftStore,
        emoji_packs: EmojiPackManager | None = None,
    ) -> None:
        self.api = api
        self.drafts = drafts
        self.resolver = ImageResolver()
        self.album = AlbumCollector(self._on_album)
        self.emoji_packs = emoji_packs

    async def aclose(self) -> None:
        await self.resolver.aclose()

    # ---------- entry ----------

    async def handle(self, upd: dict[str, Any]) -> None:
        msg = upd.get("message")
        if not msg:
            return
        # album path
        if self.album.offer(msg):
            return
        # single-message path
        await self._handle_single(msg)

    async def _handle_single(self, msg: dict[str, Any]) -> None:
        chat_id = msg["chat"]["id"]

        # MD-as-file path: a .md/.markdown/.txt document. Takes precedence
        # over the caption — the caption (if any) becomes the human title.
        doc_text = await self._maybe_load_md_document(msg, chat_id)
        if doc_text is not None:
            if doc_text:
                await self._render_preview(
                    chat_id, msg["message_id"], doc_text, [msg],
                )
            return

        text: str | None = msg.get("text") or msg.get("caption")
        if not text:
            return
        if text.startswith("/start") or text.startswith("/help"):
            await self.api.call("sendMessage", {"chat_id": chat_id, "text": WELCOME})
            return
        if text.startswith("/"):
            return
        entities = (
            msg.get("entities")
            if msg.get("text") is not None
            else msg.get("caption_entities")
        )
        await self._render_preview(
            chat_id,
            msg["message_id"],
            text,
            [msg],
            entities=entities or [],
        )

    async def _maybe_load_md_document(
        self, msg: dict[str, Any], chat_id: int,
    ) -> str | None:
        doc = msg.get("document")
        if not doc:
            return None
        name = (doc.get("file_name") or "").lower()
        mime = (doc.get("mime_type") or "").lower()
        is_md = (
            mime in {"text/markdown", "text/x-markdown", "text/plain"}
            or name.endswith((".md", ".markdown", ".txt"))
        )
        if not is_md:
            return None
        # 1 MB cap — sendRichMessage won't accept anything close to that anyway
        size = doc.get("file_size") or 0
        if size and size > 1_000_000:
            await self.api.call("sendMessage", {
                "chat_id": chat_id,
                "text": f"⚠️ Файл слишком большой: {size} байт. Максимум — 1 МБ.",
                "reply_parameters": {"message_id": msg["message_id"]},
            })
            return ""  # handled, but nothing to render
        try:
            info = await self.api.call("getFile", {"file_id": doc["file_id"]})
            raw = await self.api.download_file(info["file_path"])
        except Exception as e:
            log.exception("could not fetch MD document")
            await self.api.call("sendMessage", {
                "chat_id": chat_id,
                "text": f"❌ Не удалось скачать файл: {e}",
                "reply_parameters": {"message_id": msg["message_id"]},
            })
            return ""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")

    async def _on_album(self, msgs: list[dict[str, Any]]) -> None:
        # caption is on the first message only
        first = msgs[0]
        text = first.get("caption") or ""
        chat_id = first["chat"]["id"]
        if not text.strip():
            await self.api.call("sendMessage", {
                "chat_id": chat_id,
                "text": "📭 Альбом получен, но в подписи нет разметки — рендерить нечего.",
            })
            return
        await self._render_preview(
            chat_id,
            first["message_id"],
            text,
            msgs,
            entities=first.get("caption_entities") or [],
        )

    # ---------- rendering ----------

    async def _render_preview(
        self,
        chat_id: int,
        reply_to: int,
        md: str,
        carrier_msgs: list[dict[str, Any]],
        *,
        entities: list[dict[str, Any]] | None = None,
    ) -> None:
        del carrier_msgs  # RichMessage media currently accepts HTTP(S) URLs only.
        if not md.strip():
            await self.api.call("sendMessage", {
                "chat_id": chat_id,
                "text": "🤷 Нечего рендерить.",
                "reply_parameters": {"message_id": reply_to},
            })
            return

        try:
            md_with_user_emoji = _inject_custom_emoji_entities(
                md, entities or [],
            )
            rendered_md = await self._expand_emoji_mosaics(md_with_user_emoji)
        except Exception as e:
            log.warning("could not build emoji mosaic: %s", e)
            try:
                await self.api.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"🚫 Не удалось создать мозаику: {e}",
                    "reply_parameters": {"message_id": reply_to},
                })
            except BotAPINetworkError as report_error:
                log.error("could not report mosaic failure: %s", report_error)
            return

        # InputRichMessage accepts exactly one of `markdown` or `html`.
        # `blocks` is the response-only RichMessage representation.
        payload = {"markdown": rendered_md}

        # First send the preview *without* a keyboard — we don't have a token
        # yet (it'll be derived from the returned message_id pairing). Then
        # mint the draft and attach the keyboard via editMessageReplyMarkup.
        try:
            sent = await self.api.call("sendRichMessage", {
                "chat_id": chat_id,
                "rich_message": payload,
                "reply_parameters": {"message_id": reply_to},
            })
        except BotAPIError as e:
            log.exception("sendRichMessage failed")
            try:
                await self.api.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        f"⚠️ Telegram отклонил сообщение.\n"
                        f"{e.code}: {e.description}"
                    ),
                    "reply_parameters": {"message_id": reply_to},
                })
            except BotAPINetworkError as report_error:
                log.error("could not report Telegram rejection: %s", report_error)
            return
        except BotAPINetworkError as e:
            log.error("sendRichMessage network failure: %s", e)
            return

        preview_mid = sent.get("message_id")
        if preview_mid is not None:
            user_id = self._owner_id_from_reply(sent) or chat_id
            draft = self.drafts.create(
                user_id=user_id,
                payload=payload,
                preview_chat_id=chat_id,
                preview_message_id=preview_mid,
            )
            try:
                await self.api.call("editMessageReplyMarkup", {
                    "chat_id": chat_id,
                    "message_id": preview_mid,
                    "reply_markup": build_keyboard(draft.token),
                })
            except (BotAPIError, BotAPINetworkError) as e:
                log.warning("could not attach publish keyboard: %s", e)

    async def _expand_emoji_mosaics(self, md: str) -> str:
        matches = list(_EMOJI_URL_RE.finditer(md))
        if not matches:
            return md
        if self.emoji_packs is None:
            raise RuntimeError(
                "custom emoji недоступны: не настроен владелец Premium"
            )

        parts: list[str] = []
        cursor = 0
        for match in matches:
            if match.start() < cursor:
                continue
            parts.append(md[cursor:match.start()])
            cols = int(match.group("cols"))
            rows = int(match.group("rows"))
            url = match.group("url")
            captions, replacement_end = _consume_mosaic_captions(
                md, match.end(), rows,
            )
            resolved = await self.resolver.resolve(url, album_index={})
            if resolved.data is None:
                raise ImageResolutionError(
                    f"по ссылке {url} не удалось получить изображение"
                )
            emoji_ids = await self.emoji_packs.emoji_ids_for_mosaic(
                resolved.data, cols, rows,
            )
            parts.append(_emoji_mosaic_markdown(
                cols, rows, emoji_ids, captions=captions,
            ))
            cursor = replacement_end
        parts.append(md[cursor:])
        return "".join(parts)

    @staticmethod
    def _owner_id_from_reply(sent: dict[str, Any]) -> int | None:
        chat = sent.get("chat") or {}
        if chat.get("type") == "private":
            return chat.get("id")
        return None


def _emoji_mosaic_markdown(
    cols: int,
    rows: int,
    custom_emoji_ids: list[str],
    *,
    captions: list[str] | None = None,
) -> str:
    expected = cols * rows
    if len(custom_emoji_ids) != expected:
        raise ValueError(
            f"ожидалось {expected} emoji ID для сетки {cols}x{rows}, "
            f"получено {len(custom_emoji_ids)}"
        )
    caption_start = (
        max(0, (rows - len(captions)) // 2)
        if captions is not None
        else 0
    )
    lines: list[str] = []
    for row in range(rows):
        offset = row * cols
        line = "".join(
            f"![{FALLBACK_EMOJI}](tg://emoji?id={emoji_id})"
            for emoji_id in custom_emoji_ids[offset:offset + cols]
        )
        caption_index = row - caption_start
        if (
            captions is not None
            and 0 <= caption_index < len(captions)
            and captions[caption_index]
        ):
            line += f"&nbsp;{captions[caption_index]}"
        lines.append(line)
    # A plain newline is folded into a space inside a Rich Markdown
    # paragraph. Rich Markdown accepts HTML, so use an explicit line break
    # to keep mosaic rows adjacent without paragraph spacing.
    return "<br>\n".join(lines)


def _consume_mosaic_captions(
    md: str,
    start: int,
    rows: int,
) -> tuple[list[str] | None, int]:
    """Consume up to `rows` immediately-following `| caption` lines."""
    cursor = start
    captions: list[str] = []
    for _ in range(rows):
        match = re.match(r"\n[ \t]*\|[ \t]?(?P<caption>[^\n]*)", md[cursor:])
        if match is None:
            break
        captions.append(match.group("caption").rstrip())
        cursor += match.end()
    return (captions or None), cursor


def _inject_custom_emoji_entities(
    text: str,
    entities: list[dict[str, Any]],
) -> str:
    """Convert Telegram custom-emoji entities to Rich Markdown syntax."""
    replacements: list[tuple[int, int, str]] = []
    for entity in entities:
        if entity.get("type") != "custom_emoji":
            continue
        emoji_id = entity.get("custom_emoji_id")
        if not emoji_id:
            continue
        start = _utf16_offset_to_index(text, int(entity.get("offset", 0)))
        end = _utf16_offset_to_index(
            text,
            int(entity.get("offset", 0)) + int(entity.get("length", 0)),
        )
        alternative = text[start:end] or FALLBACK_EMOJI
        if "]" in alternative or "\n" in alternative:
            alternative = FALLBACK_EMOJI
        replacements.append((
            start,
            end,
            f"![{alternative}](tg://emoji?id={emoji_id})",
        ))

    out = text
    for start, end, replacement in sorted(replacements, reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def _utf16_offset_to_index(text: str, offset: int) -> int:
    if offset <= 0:
        return 0
    units = 0
    for index, char in enumerate(text):
        char_units = len(char.encode("utf-16-le")) // 2
        if units + char_units > offset:
            return index
        units += char_units
        if units == offset:
            return index + 1
    return len(text)
