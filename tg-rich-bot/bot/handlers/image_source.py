"""Resolve image references from MD into something the Bot API can ingest.

Three sources we support:
  - filename ref `![alt](photo1.jpg)` paired with an attached album item
    whose `file_name` matches → resolves to a Telegram `file_id`.
  - http(s) URL `![alt](https://example.com/x.png)` → downloads bytes,
    returns them as an in-memory upload.
  - bare `file_id` (rare; useful for re-using already-uploaded images).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from typing import Any
from urllib.parse import urljoin

import httpx
from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)


@dataclass
class ResolvedImage:
    """Either a file_id to reference, or raw bytes to upload."""
    src: str                 # original src from MD (for diagnostics)
    file_id: str | None = None
    data: bytes | None = None
    mime: str | None = None
    filename: str | None = None

    def as_input_file(self) -> dict[str, Any]:
        """Shape suitable for putting into a `photo` block once Telegram
        accepts file_id / URL references inside RichMessage payloads."""
        if self.file_id is not None:
            return {"file_id": self.file_id}
        # Multipart attachment: caller is responsible for adding the
        # bytes to the request's `files=` and referencing by attach://
        return {"attach": True}


_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)
_FILE_ID_HINT_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")  # rough heuristic
_HTML_MIMES = {"text/html", "application/xhtml+xml"}


class ImageResolver:
    """Pulls image data from URLs or matches against the inbound album."""

    def __init__(self, *, max_url_bytes: int = 10 * 1024 * 1024) -> None:
        self._max = max_url_bytes
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def resolve(
        self, src: str, *, album_index: dict[str, dict[str, Any]],
    ) -> ResolvedImage:
        """Resolve one MD `src` to a ResolvedImage.

        `album_index` maps lowercase filename → photo dict (the largest
        size object from `message.photo[-1]`, or `message.document` for
        files sent as documents).
        """
        # 1. attached file by name
        key = src.strip().lower()
        if key in album_index:
            obj = album_index[key]
            return ResolvedImage(
                src=src, file_id=obj["file_id"], filename=src,
            )

        # 2. http(s)
        if _HTTP_RE.match(src):
            data, mime = await self._download(src)
            filename = src.rsplit("/", 1)[-1] or "image"
            return ResolvedImage(src=src, data=data, mime=mime, filename=filename)

        # 3. looks like a raw file_id
        if _FILE_ID_HINT_RE.match(src) and "." not in src and "/" not in src:
            return ResolvedImage(src=src, file_id=src)

        raise ImageResolutionError(
            f"could not resolve image {src!r}: no attached file with that "
            f"name, not an http(s) URL, not a file_id."
        )

    async def _download(self, url: str) -> tuple[bytes, str | None]:
        resp = await self._get(url)
        mime = _response_mime(resp)
        if mime in _HTML_MIMES or _looks_like_html(resp.content):
            image_url = _extract_page_image_url(resp.text, str(resp.url))
            if image_url is None:
                raise ImageResolutionError(
                    f"страница {url} не содержит прямой ссылки на изображение"
                )
            resp = await self._get(image_url)
            mime = _response_mime(resp)

        body = resp.content
        try:
            with Image.open(BytesIO(body)) as image:
                image.verify()
                detected_mime = Image.MIME.get(image.format or "")
        except (UnidentifiedImageError, OSError) as e:
            raise ImageResolutionError(
                f"по ссылке {url} получен не файл изображения"
            ) from e
        return body, detected_mime or mime

    async def _get(self, url: str) -> httpx.Response:
        try:
            resp = await self._client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 tg-rich-bot/0.1"},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ImageResolutionError(
                f"не удалось скачать {url}: {e!r}"
            ) from e
        cl = resp.headers.get("content-length")
        try:
            content_length = int(cl) if cl else None
        except ValueError:
            content_length = None
        if content_length is not None and content_length > self._max:
            raise ImageResolutionError(
                f"файл по ссылке {url} больше лимита {self._max} байт"
            )
        if len(resp.content) > self._max:
            raise ImageResolutionError(
                f"файл по ссылке {url} больше лимита {self._max} байт"
            )
        return resp


class ImageResolutionError(RuntimeError):
    pass


def _response_mime(resp: httpx.Response) -> str | None:
    return (
        resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        or None
    )


def _looks_like_html(body: bytes) -> bool:
    prefix = body[:512].lstrip().lower()
    return prefix.startswith((b"<!doctype html", b"<html", b"<head"))


class _PageImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key.lower(): value for key, value in attrs if value}
        if tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {
                "og:image",
                "og:image:url",
                "og:image:secure_url",
                "twitter:image",
                "twitter:image:src",
            }:
                self._add(values.get("content"))
        elif tag.lower() == "link":
            rel = (values.get("rel") or "").lower().split()
            if "image_src" in rel:
                self._add(values.get("href"))

    def _add(self, value: str | None) -> None:
        if value and value not in self.candidates:
            self.candidates.append(value)


def _extract_page_image_url(html: str, page_url: str) -> str | None:
    parser = _PageImageParser()
    parser.feed(html)
    for candidate in parser.candidates:
        resolved = urljoin(page_url, candidate)
        if _HTTP_RE.match(resolved):
            return resolved
    return None


# ---------- album indexing ----------

def build_album_index(messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index `file_name` (lowercased) → media object across an album.

    Photos sent natively don't carry filenames — the Telegram client
    converts them. We therefore also index synthetic positional aliases
    `photo1.jpg`, `photo2.jpg`, … in the order messages arrived, so a
    user typing `![](photo1.jpg)` can reference the first attachment
    regardless of how it was sent.
    """
    out: dict[str, dict[str, Any]] = {}
    photo_n = 0
    for msg in messages:
        media: dict[str, Any] | None = None
        kind: str | None = None
        if "photo" in msg:
            # photo is a list of sizes; take the largest
            media = max(msg["photo"], key=lambda p: p.get("file_size", 0) or 0)
            kind = "photo"
        elif "document" in msg and (msg["document"].get("mime_type") or "").startswith("image/"):
            media = msg["document"]
            kind = "document"
        if media is None:
            continue

        # named filename (documents have one, native photos don't)
        name = (media.get("file_name") or "").strip().lower()
        if name:
            out[name] = media

        # positional alias — only for `photo` items so they're predictable
        if kind == "photo":
            photo_n += 1
            out[f"photo{photo_n}.jpg"] = media
            out[f"photo{photo_n}"] = media
    return out
