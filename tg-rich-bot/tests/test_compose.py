from bot.handlers.compose import (
    ComposeHandler,
    _consume_mosaic_captions,
    _emoji_mosaic_markdown,
    _inject_custom_emoji_entities,
)
from bot.handlers.drafts import DraftStore
from bot.handlers.image_source import ResolvedImage


class FakeAPI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict):
        self.calls.append((method, params))
        if method == "sendRichMessage":
            return {"message_id": 20, "chat": {"id": 42, "type": "private"}}
        return True


async def test_preview_uses_documented_input_rich_message_shape():
    api = FakeAPI()
    handler = ComposeHandler(api, DraftStore())  # type: ignore[arg-type]
    try:
        await handler._render_preview(
            chat_id=42,
            reply_to=10,
            md="# Heading\n\n**bold**",
            carrier_msgs=[],
        )
    finally:
        await handler.aclose()

    method, params = api.calls[0]
    assert method == "sendRichMessage"
    assert params["rich_message"] == {
        "markdown": "# Heading\n\n**bold**",
    }
    assert "blocks" not in params["rich_message"]


class FakeResolver:
    async def resolve(self, src: str, *, album_index: dict):
        assert src == "https://example.com/logo.png"
        assert album_index == {}
        return ResolvedImage(src=src, data=b"png")

    async def aclose(self):
        pass


class FakeEmojiPacks:
    async def emoji_ids_for_mosaic(self, data: bytes, cols: int, rows: int):
        assert data == b"png"
        assert (cols, rows) == (2, 2)
        return ["id1", "id2", "id3", "id4"]


async def test_preview_expands_url_mosaic_to_custom_emoji_markdown():
    api = FakeAPI()
    handler = ComposeHandler(
        api,
        DraftStore(),
        emoji_packs=FakeEmojiPacks(),  # type: ignore[arg-type]
    )
    handler.resolver = FakeResolver()  # type: ignore[assignment]
    try:
        await handler._render_preview(
            chat_id=42,
            reply_to=10,
            md="До\n\n![[emoji:2x2]](https://example.com/logo.png)\n\nПосле",
            carrier_msgs=[],
        )
    finally:
        await handler.aclose()

    _, params = api.calls[0]
    assert params["rich_message"]["markdown"] == (
        "До\n\n"
        "![⬜](tg://emoji?id=id1)![⬜](tg://emoji?id=id2)<br>\n"
        "![⬜](tg://emoji?id=id3)![⬜](tg://emoji?id=id4)"
        "\n\nПосле"
    )


def test_emoji_mosaic_markdown_checks_id_count():
    assert _emoji_mosaic_markdown(1, 2, ["a", "b"]) == (
        "![⬜](tg://emoji?id=a)<br>\n![⬜](tg://emoji?id=b)"
    )


async def test_preview_places_caption_after_each_mosaic_row():
    api = FakeAPI()
    handler = ComposeHandler(
        api,
        DraftStore(),
        emoji_packs=FakeEmojiPacks(),  # type: ignore[arg-type]
    )
    handler.resolver = FakeResolver()  # type: ignore[assignment]
    try:
        await handler._render_preview(
            chat_id=42,
            reply_to=10,
            md=(
                "![[emoji:2x2]](https://example.com/logo.png)\n"
                "| *Илья Полосухин*\n"
                "| NEAR\n"
                "\nПосле"
            ),
            carrier_msgs=[],
        )
    finally:
        await handler.aclose()

    _, params = api.calls[0]
    assert params["rich_message"]["markdown"] == (
        "![⬜](tg://emoji?id=id1)![⬜](tg://emoji?id=id2)"
        "&nbsp;*Илья Полосухин*<br>\n"
        "![⬜](tg://emoji?id=id3)![⬜](tg://emoji?id=id4)"
        "&nbsp;NEAR\n"
        "\nПосле"
    )


def test_consume_mosaic_captions_stops_at_row_count():
    md = "marker\n| first\n| second\n| untouched"
    captions, end = _consume_mosaic_captions(md, len("marker"), rows=2)
    assert captions == ["first", "second"]
    assert md[end:] == "\n| untouched"


def test_mosaic_captions_are_vertically_centered():
    ids = [f"id{i}" for i in range(10)]
    rendered = _emoji_mosaic_markdown(
        1,
        10,
        ids,
        captions=["Title", "Subtitle", "Company"],
    )
    lines = rendered.split("<br>\n")

    assert "&nbsp;" not in lines[2]
    assert lines[3].endswith("&nbsp;Title")
    assert lines[4].endswith("&nbsp;Subtitle")
    assert lines[5].endswith("&nbsp;Company")
    assert "&nbsp;" not in lines[6]


def test_user_custom_emoji_entity_becomes_rich_markdown():
    text = "Привет 😀 мир"
    # Cyrillic and spaces are one UTF-16 unit each; 😀 occupies two.
    rendered = _inject_custom_emoji_entities(text, [{
        "type": "custom_emoji",
        "offset": 7,
        "length": 2,
        "custom_emoji_id": "emoji-123",
    }])
    assert rendered == (
        "Привет ![😀](tg://emoji?id=emoji-123) мир"
    )


async def test_message_entities_are_preserved_in_preview():
    api = FakeAPI()
    handler = ComposeHandler(api, DraftStore())  # type: ignore[arg-type]
    try:
        await handler.handle({"message": {
            "message_id": 10,
            "chat": {"id": 42},
            "text": "A😀B",
            "entities": [{
                "type": "custom_emoji",
                "offset": 1,
                "length": 2,
                "custom_emoji_id": "user-emoji",
            }],
        }})
    finally:
        await handler.aclose()

    _, params = api.calls[0]
    assert params["rich_message"]["markdown"] == (
        "A![😀](tg://emoji?id=user-emoji)B"
    )
