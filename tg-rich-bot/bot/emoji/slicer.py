"""Slice a source image into an NxM grid of PNG tiles for custom emoji.

Telegram requires custom_emoji tiles to be exactly 100x100 PNG with
transparent or solid background. We resize the input so each tile fits
the 100x100 cell, then export per-cell PNG bytes.

We also expose `mosaic_signature(...)` — a stable hash over (cols, rows,
content bytes) so the upstream cache can skip re-slicing AND re-uploading
when the same image+grid is reused.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps


TILE_PX = 100
MAX_DIM = 10  # 10x10 cap per user policy
SIGNATURE_VERSION = b"cover-v1"


@dataclass(frozen=True)
class MosaicTile:
    row: int
    col: int
    png: bytes


def mosaic_signature(image_bytes: bytes, cols: int, rows: int) -> str:
    """Stable hex hash for cache lookup."""
    h = hashlib.sha256()
    h.update(SIGNATURE_VERSION)
    h.update(cols.to_bytes(4, "big"))
    h.update(rows.to_bytes(4, "big"))
    h.update(image_bytes)
    return h.hexdigest()[:32]


def slice_mosaic(image_bytes: bytes, cols: int, rows: int) -> list[MosaicTile]:
    """Resize and slice an image into rows*cols 100x100 PNG tiles.

    Returns tiles in row-major order so the caller can pass the matching
    custom_emoji_ids list to `emoji_mosaic_block` 1:1.
    """
    if cols < 1 or rows < 1:
        raise ValueError(f"mosaic dims must be >= 1, got {cols}x{rows}")
    if cols > MAX_DIM or rows > MAX_DIM:
        raise ValueError(f"mosaic dims capped at {MAX_DIM}x{MAX_DIM}, got {cols}x{rows}")

    src = Image.open(BytesIO(image_bytes))
    src = src.convert("RGBA")

    target_w = cols * TILE_PX
    target_h = rows * TILE_PX
    # Fill the whole grid while preserving aspect ratio. Transparent padding
    # creates visible indentation before the mosaic and a gap before captions.
    canvas = ImageOps.fit(
        src,
        (target_w, target_h),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    tiles: list[MosaicTile] = []
    for r in range(rows):
        for c in range(cols):
            box = (c * TILE_PX, r * TILE_PX, (c + 1) * TILE_PX, (r + 1) * TILE_PX)
            tile = canvas.crop(box)
            buf = BytesIO()
            tile.save(buf, format="PNG", optimize=True)
            tiles.append(MosaicTile(row=r, col=c, png=buf.getvalue()))
    return tiles
