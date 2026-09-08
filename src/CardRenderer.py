from __future__ import annotations

from io import BytesIO
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps


CARD_WIDTH = 900
COVER_HEIGHT = 900
PANEL_HEIGHT = 360
BG = (18, 18, 18)
TEXT = (255, 255, 255)
MUTED = (179, 179, 179)
BAR_BG = (83, 83, 83)
BAR_FILL = (30, 215, 96)


def render_track_card(data: dict[str, Any], downloader: requests.Session) -> bytes:
    cover = _load_image(data["TA"], downloader, (CARD_WIDTH, COVER_HEIGHT))
    card = Image.new("RGB", (CARD_WIDTH, COVER_HEIGHT + PANEL_HEIGHT), BG)
    card.paste(cover, (0, 0))

    draw = ImageDraw.Draw(card)
    title_font = _font(54)
    meta_font = _font(32)

    title_y = COVER_HEIGHT + 28
    artists_y = title_y + 60
    avatars_y = artists_y + 60
    time_y = COVER_HEIGHT + PANEL_HEIGHT - 76

    title = data["TrackName"]
    artists = " · ".join(artist["name"] for artist in data["Artists"])

    draw.text((28, title_y), title, fill=TEXT, font=title_font)
    draw.text((28, artists_y), artists, fill=MUTED, font=meta_font)

    _draw_avatar_grid(card, data["Artists"], downloader, (28, avatars_y))

    left_time = data["TN"]
    total_time = data["TT"]
    draw.text((28, time_y), f"{left_time} / {total_time}", fill=MUTED, font=title_font)
    _draw_progress_bar(
        draw,
        x=270,
        y=time_y + 22,
        width=420,
        height=10,
        progress_ms=data["ProgressMS"],
        duration_ms=data["DurationMS"],
    )

    out = BytesIO()
    card.save(out, format="JPEG", quality=94)
    return out.getvalue()


def build_caption_html(data: dict[str, Any]) -> str:
    lines = []
    for artist in data["Artists"]:
        url = artist.get("url") or ""
        name = _escape_html(artist["name"])
        if url:
            lines.append(f'<a href="{_escape_html(url)}">{name}</a>')
        else:
            lines.append(name)
    return "\n".join(lines)


def _draw_avatar_grid(
    card: Image.Image,
    artists: list[dict[str, Any]],
    downloader: requests.Session,
    origin: tuple[int, int],
) -> None:
    x, y = origin
    size = 84
    gap_x = 12
    gap_y = 12
    columns = 3
    for index, artist in enumerate(artists[:9]):
        avatar_url = artist.get("image") or artist.get("TA") or ""
        avatar = _load_avatar(avatar_url, downloader, size)
        if avatar is None:
            continue
        col = index % columns
        row = index // columns
        pos_x = x + col * (size + gap_x)
        pos_y = y + row * (size + gap_y)
        card.paste(avatar, (pos_x, pos_y), avatar)


def _draw_progress_bar(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    progress_ms: int,
    duration_ms: int,
) -> None:
    ratio = 0.0 if duration_ms <= 0 else max(0.0, min(progress_ms / duration_ms, 1.0))
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=BAR_BG)
    draw.rounded_rectangle((x, y, x + int(width * ratio), y + height), radius=height // 2, fill=BAR_FILL)


def _load_image(url: str, downloader: requests.Session, size: tuple[int, int]) -> Image.Image:
    response = downloader.get(url, timeout=30)
    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as source:
        return ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def _load_avatar(url: str, downloader: requests.Session, size: int) -> Image.Image | None:
    if not url:
        return None
    response = downloader.get(url, timeout=30)
    response.raise_for_status()
    with Image.open(BytesIO(response.content)) as source:
        avatar = ImageOps.fit(source.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)

    rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rounded.paste(avatar, (0, 0), mask)

    ring = ImageDraw.Draw(rounded)
    ring.ellipse((1, 1, size - 2, size - 2), outline=(255, 255, 255, 220), width=3)
    return rounded


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
