from pathlib import Path

from bot.api import BotAPIError
from bot.emoji.pack import EmojiPackManager, MosaicCache
from bot.emoji.slicer import MosaicTile


class FakeAPI:
    def __init__(self) -> None:
        self.packs: dict[str, list[dict[str, str]]] = {}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, method: str, params: dict, files=None):
        self.calls.append((method, params))
        if method == "uploadStickerFile":
            return {"file_id": f"file-{len(self.calls)}"}
        if method == "getStickerSet":
            pack = self.packs.get(params["name"])
            if pack is None:
                raise BotAPIError(method, 400, "Bad Request: STICKERSET_INVALID")
            return {"stickers": list(pack)}
        if method == "createNewStickerSet":
            self.packs[params["name"]] = [
                {"custom_emoji_id": f"id-{sticker['sticker']}"}
                for sticker in params["stickers"]
            ]
            return True
        if method == "addStickerToSet":
            pack = self.packs.get(params["name"])
            if pack is None:
                raise BotAPIError(method, 400, "Bad Request: STICKERSET_INVALID")
            pack.append({
                "custom_emoji_id": f"id-{params['sticker']['sticker']}",
            })
            return True
        raise AssertionError(method)


def _manager(api: FakeAPI, tmp_path: Path) -> EmojiPackManager:
    return EmojiPackManager(
        api,  # type: ignore[arg-type]
        owner_id=1,
        bot_username="test_bot",
        cache=MosaicCache(tmp_path / "cache.json"),
    )


async def test_new_pack_is_created_with_all_tiles(tmp_path):
    api = FakeAPI()
    manager = _manager(api, tmp_path)
    tiles = [MosaicTile(0, col, b"png") for col in range(3)]

    ids = await manager._create_pack_and_get_ids(tiles)

    create = next(params for method, params in api.calls
                  if method == "createNewStickerSet")
    assert len(create["stickers"]) == 3
    assert not any(method == "addStickerToSet" for method, _ in api.calls)
    assert len(ids) == 3


async def test_each_mosaic_creates_a_new_pack(tmp_path):
    api = FakeAPI()
    manager = _manager(api, tmp_path)
    tiles = [MosaicTile(0, col, b"png") for col in range(2)]

    await manager._create_pack_and_get_ids(tiles)
    await manager._create_pack_and_get_ids(tiles)

    creates = [
        params for method, params in api.calls
        if method == "createNewStickerSet"
    ]
    assert len(creates) == 2
    assert creates[0]["name"] != creates[1]["name"]


async def test_pack_over_50_tiles_appends_the_rest(tmp_path):
    api = FakeAPI()
    manager = _manager(api, tmp_path)
    tiles = [MosaicTile(row // 10, row % 10, b"png") for row in range(60)]

    ids = await manager._create_pack_and_get_ids(tiles)

    create = next(params for method, params in api.calls
                  if method == "createNewStickerSet")
    assert len(create["stickers"]) == 50
    assert len([1 for method, _ in api.calls if method == "addStickerToSet"]) == 10
    assert len(ids) == 60
