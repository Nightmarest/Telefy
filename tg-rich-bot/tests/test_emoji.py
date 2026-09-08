from io import BytesIO

import pytest
from PIL import Image

from bot.emoji.pack import MosaicCache
from bot.emoji.slicer import TILE_PX, mosaic_signature, slice_mosaic


# ---------- slicer ----------

def _make_png(width: int, height: int, color=(255, 0, 0, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_slice_3x3_produces_9_tiles_each_100px():
    src = _make_png(300, 300)
    tiles = slice_mosaic(src, cols=3, rows=3)
    assert len(tiles) == 9
    # row-major
    assert [(t.row, t.col) for t in tiles] == [
        (r, c) for r in range(3) for c in range(3)
    ]
    for t in tiles:
        img = Image.open(BytesIO(t.png))
        assert img.size == (TILE_PX, TILE_PX)


def test_slice_resizes_oversized_input():
    src = _make_png(2000, 1000)
    tiles = slice_mosaic(src, cols=4, rows=2)
    assert len(tiles) == 8
    for t in tiles:
        assert Image.open(BytesIO(t.png)).size == (TILE_PX, TILE_PX)


def test_slice_fills_grid_without_transparent_padding():
    src = _make_png(100, 200, (0, 200, 0, 255))
    tiles = slice_mosaic(src, cols=3, rows=3)
    for tile in tiles:
        image = Image.open(BytesIO(tile.png))
        assert image.getextrema()[3] == (255, 255)


def test_slice_rejects_bad_dims():
    with pytest.raises(ValueError):
        slice_mosaic(_make_png(50, 50), cols=0, rows=2)
    with pytest.raises(ValueError):
        slice_mosaic(_make_png(50, 50), cols=11, rows=2)


def test_slice_accepts_non_square_grid():
    src = _make_png(500, 200)
    tiles = slice_mosaic(src, cols=5, rows=2)
    assert len(tiles) == 10
    rows = {t.row for t in tiles}
    cols = {t.col for t in tiles}
    assert rows == {0, 1} and cols == {0, 1, 2, 3, 4}


def test_signature_stable_across_calls():
    src = _make_png(100, 100)
    assert mosaic_signature(src, 3, 3) == mosaic_signature(src, 3, 3)


def test_signature_changes_with_grid():
    src = _make_png(100, 100)
    assert mosaic_signature(src, 3, 3) != mosaic_signature(src, 3, 4)


def test_signature_changes_with_bytes():
    a = _make_png(100, 100, (255, 0, 0, 255))
    b = _make_png(100, 100, (0, 0, 255, 255))
    assert mosaic_signature(a, 3, 3) != mosaic_signature(b, 3, 3)


# ---------- MosaicCache ----------

def test_cache_persists_round_trip(tmp_path):
    path = tmp_path / "cache.json"
    c1 = MosaicCache(path)
    assert c1.get("sig1") is None
    c1.put("sig1", ["id1", "id2", "id3"])
    # fresh instance loads from disk
    c2 = MosaicCache(path)
    assert c2.get("sig1") == ["id1", "id2", "id3"]


def test_cache_handles_corrupt_file(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not valid json {{{")
    c = MosaicCache(path)
    assert c.get("anything") is None
    # still writable
    c.put("k", ["v"])
    assert MosaicCache(path).get("k") == ["v"]


def test_cache_overwrites_existing_key(tmp_path):
    path = tmp_path / "cache.json"
    c = MosaicCache(path)
    c.put("sig", ["a"])
    c.put("sig", ["b", "c"])
    assert MosaicCache(path).get("sig") == ["b", "c"]
