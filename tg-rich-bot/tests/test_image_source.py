import asyncio
from io import BytesIO

import httpx
import pytest
from PIL import Image

from bot.handlers.image_source import (
    ImageResolutionError, ImageResolver, _extract_page_image_url,
    build_album_index,
)
from bot.util.album import AlbumCollector


# ---------- AlbumCollector ----------

@pytest.mark.asyncio
async def test_album_collector_groups_by_media_group_id():
    received: list[list[dict]] = []

    async def on_album(msgs):
        received.append(msgs)

    coll = AlbumCollector(on_album, flush_after=0.05)
    assert coll.offer({"media_group_id": "g1", "message_id": 2})
    assert coll.offer({"media_group_id": "g1", "message_id": 1})
    assert coll.offer({"media_group_id": "g2", "message_id": 3})
    # not an album → returns False, does not buffer
    assert not coll.offer({"message_id": 4})

    await asyncio.sleep(0.15)
    assert len(received) == 2
    # sorted by message_id
    assert [m["message_id"] for m in received[0]] == [1, 2] or \
           [m["message_id"] for m in received[1]] == [1, 2]


@pytest.mark.asyncio
async def test_album_collector_resets_timer_on_late_arrivals():
    fired = asyncio.Event()
    received: list[int] = []

    async def on_album(msgs):
        received.append(len(msgs))
        fired.set()

    coll = AlbumCollector(on_album, flush_after=0.08)
    coll.offer({"media_group_id": "g", "message_id": 1})
    await asyncio.sleep(0.05)
    coll.offer({"media_group_id": "g", "message_id": 2})  # resets timer
    await asyncio.sleep(0.05)
    coll.offer({"media_group_id": "g", "message_id": 3})  # resets again
    await asyncio.wait_for(fired.wait(), timeout=0.5)
    assert received == [3]


# ---------- build_album_index ----------

def test_album_index_positional_photo_aliases():
    msgs = [
        {"photo": [{"file_id": "small_A", "file_size": 100},
                   {"file_id": "big_A", "file_size": 9000}]},
        {"photo": [{"file_id": "B", "file_size": 5000}]},
    ]
    idx = build_album_index(msgs)
    assert idx["photo1.jpg"]["file_id"] == "big_A"
    assert idx["photo1"]["file_id"] == "big_A"
    assert idx["photo2.jpg"]["file_id"] == "B"
    assert idx["photo2"]["file_id"] == "B"


def test_album_index_document_by_filename():
    msgs = [
        {"document": {
            "file_id": "doc_X", "file_name": "Cover.PNG", "mime_type": "image/png",
        }},
    ]
    idx = build_album_index(msgs)
    assert "cover.png" in idx
    assert idx["cover.png"]["file_id"] == "doc_X"


def test_album_index_skips_non_image_documents():
    msgs = [
        {"document": {
            "file_id": "z", "file_name": "note.pdf", "mime_type": "application/pdf",
        }},
    ]
    assert build_album_index(msgs) == {}


def test_album_index_mixed_photo_and_document():
    msgs = [
        {"photo": [{"file_id": "P1", "file_size": 1}]},
        {"document": {
            "file_id": "D1", "file_name": "logo.jpg", "mime_type": "image/jpeg",
        }},
        {"photo": [{"file_id": "P2", "file_size": 1}]},
    ]
    idx = build_album_index(msgs)
    assert idx["photo1.jpg"]["file_id"] == "P1"
    assert idx["photo2.jpg"]["file_id"] == "P2"
    assert idx["logo.jpg"]["file_id"] == "D1"


# ---------- ImageResolver ----------

@pytest.mark.asyncio
async def test_resolver_matches_album_filename():
    r = ImageResolver()
    try:
        idx = {"photo1.jpg": {"file_id": "FID_1"}}
        ri = await r.resolve("photo1.jpg", album_index=idx)
        assert ri.file_id == "FID_1"
        assert ri.data is None
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_resolver_filename_case_insensitive():
    r = ImageResolver()
    try:
        idx = {"cover.png": {"file_id": "F"}}
        ri = await r.resolve("Cover.PNG", album_index=idx)
        assert ri.file_id == "F"
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_resolver_unknown_src_raises():
    r = ImageResolver()
    try:
        with pytest.raises(ImageResolutionError):
            await r.resolve("nope.jpg", album_index={})
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_resolver_file_id_heuristic():
    r = ImageResolver()
    try:
        # 25-char alphanumeric/_- string, no dots/slashes → treated as file_id
        fid = "AgACAgIAAxkBAAEABCDE123XYZ"
        ri = await r.resolve(fid, album_index={})
        assert ri.file_id == fid
    finally:
        await r.aclose()


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return buf.getvalue()


def test_extract_page_image_url_supports_open_graph_and_relative_urls():
    html = '<meta property="og:image" content="/images/photo.png">'
    assert _extract_page_image_url(html, "https://ibb.co/page") == (
        "https://ibb.co/images/photo.png"
    )


@pytest.mark.asyncio
async def test_resolver_follows_landing_page_og_image():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "ibb.co":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=(
                    '<html><head><meta property="og:image" '
                    'content="https://i.ibb.co/direct.png"></head></html>'
                ),
            )
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=_png_bytes(),
        )

    r = ImageResolver()
    await r._client.aclose()
    r._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    try:
        resolved = await r.resolve("https://ibb.co/abc", album_index={})
        assert resolved.data == _png_bytes()
        assert resolved.mime == "image/png"
        assert requested == [
            "https://ibb.co/abc",
            "https://i.ibb.co/direct.png",
        ]
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_resolver_rejects_html_without_image_metadata():
    r = ImageResolver()
    await r._client.aclose()
    r._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>no image here</body></html>",
        )),
    )
    try:
        with pytest.raises(ImageResolutionError, match="не содержит"):
            await r.resolve("https://example.com/page", album_index={})
    finally:
        await r.aclose()
