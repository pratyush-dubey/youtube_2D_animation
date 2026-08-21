"""Deterministic editorial treatments for structured documentary assets."""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


STRUCTURED_ASSET_TYPES = {
    "animated-map",
    "newspaper-document",
    "evidence-board",
    "diagram",
}


def enhance_structured_asset(path: Path, asset_type: str, seed: int) -> Path:
    """Turn an atmospheric plate into a recognizable editorial asset."""
    if asset_type not in STRUCTURED_ASSET_TYPES:
        return path

    source = Image.open(path).convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    if asset_type in {"animated-map", "diagram"}:
        result = _map_frame(source, seed)
    elif asset_type == "newspaper-document":
        result = _document_frame(source, seed)
    else:
        result = _evidence_board(source, seed)
    result.save(path, "JPEG", quality=93, subsampling=0)
    return path


def _dark_plate(source: Image.Image, blur: float = 8.0) -> Image.Image:
    plate = source.filter(ImageFilter.GaussianBlur(blur))
    plate = ImageEnhance.Color(plate).enhance(0.35)
    plate = ImageEnhance.Brightness(plate).enhance(0.3)
    tint = Image.new("RGB", plate.size, "#061611")
    return Image.blend(plate, tint, 0.58)


def _map_frame(source: Image.Image, seed: int) -> Image.Image:
    rng = random.Random(seed)
    image = _dark_plate(source, 5)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for x in range(90, 1920, 120):
        draw.line((x, 0, x, 1080), fill=(118, 159, 135, 18), width=1)
    for y in range(70, 1080, 110):
        draw.line((0, y, 1920, y), fill=(118, 159, 135, 18), width=1)

    for band in range(14):
        points = []
        center_y = 120 + band * 65
        for x in range(-50, 2001, 30):
            y = center_y + 28 * math.sin(x / 135 + band * 0.62) + rng.randint(-5, 5)
            points.append((x, y))
        draw.line(points, fill=(116, 159, 130, 65), width=2)

    region = [(390, 780), (510, 555), (735, 470), (930, 525), (1145, 390), (1505, 260)]
    draw.line(region, fill=(20, 28, 24, 210), width=15)
    draw.line(region, fill=(244, 177, 70, 255), width=5)
    for i, point in enumerate(region):
        radius = 9 if i not in {0, len(region) - 1} else 18
        draw.ellipse(
            (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
            fill=(227, 164, 61, 255) if i < len(region) - 1 else (179, 35, 43, 255),
            outline=(245, 228, 187, 230),
            width=3,
        )
    draw.arc((1410, 165, 1600, 355), 0, 360, fill=(179, 35, 43, 120), width=3)
    draw.arc((1435, 190, 1575, 330), 0, 360, fill=(179, 35, 43, 90), width=2)
    draw.polygon([(1740, 125), (1718, 182), (1762, 182)], fill=(235, 220, 187, 220))
    draw.line((1740, 145, 1740, 225), fill=(235, 220, 187, 180), width=3)
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _document_frame(source: Image.Image, seed: int) -> Image.Image:
    rng = random.Random(seed)
    background = _dark_plate(source, 12)
    paper = Image.new("RGBA", (1320, 820), (224, 214, 188, 255))
    draw = ImageDraw.Draw(paper)
    for _ in range(1900):
        x, y = rng.randrange(1320), rng.randrange(820)
        shade = rng.randrange(150, 210)
        draw.point((x, y), fill=(shade, shade - 8, shade - 20, rng.randrange(20, 55)))
    draw.rectangle((105, 90, 750, 126), fill=(36, 39, 36, 235))
    draw.rectangle((105, 148, 1060, 164), fill=(85, 83, 73, 165))
    draw.line((92, 200, 1220, 200), fill=(92, 86, 71, 130), width=3)
    for row in range(9):
        y = 255 + row * 50
        width = rng.randint(720, 1090)
        draw.rounded_rectangle((110, y, 110 + width, y + 13), 5, fill=(65, 66, 60, 150))
    draw.rounded_rectangle((92, 490, 1175, 575), 8, fill=(235, 173, 51, 70), outline=(231, 165, 44, 230), width=6)
    draw.ellipse((930, 610, 1175, 765), outline=(143, 32, 35, 190), width=12)
    paper = paper.rotate(-3.2, Image.Resampling.BICUBIC, expand=True)
    shadow = Image.new("RGBA", background.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((285, 120, 1655, 1010), 18, fill=(0, 0, 0, 175))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    composed = Image.alpha_composite(background.convert("RGBA"), shadow)
    composed.alpha_composite(paper, (300, 105))
    return composed.convert("RGB")


def _evidence_board(source: Image.Image, seed: int) -> Image.Image:
    rng = random.Random(seed)
    background = _dark_plate(source, 4).convert("RGBA")
    board = Image.new("RGBA", background.size, (9, 22, 17, 130))
    draw = ImageDraw.Draw(board)
    cards = [
        (190, 160, 700, 535, -4),
        (735, 100, 1275, 485, 3),
        (1185, 480, 1725, 915, -2),
        (350, 650, 850, 955, 2),
    ]
    centers = []
    for index, (x1, y1, x2, y2, angle) in enumerate(cards):
        width, height = x2 - x1, y2 - y1
        card = Image.new("RGBA", (width, height), (225, 216, 193, 255))
        crop_x = rng.randint(0, max(source.width - 900, 1))
        crop = source.crop((crop_x, 0, min(crop_x + 900, source.width), source.height))
        crop.thumbnail((width - 48, height - 82), Image.Resampling.LANCZOS)
        crop = ImageEnhance.Color(crop).enhance(0.15 if index != 1 else 0.55)
        card.alpha_composite(crop.convert("RGBA"), ((width - crop.width) // 2, 24))
        card_draw = ImageDraw.Draw(card)
        card_draw.rectangle((36, height - 44, width - 80, height - 31), fill=(63, 61, 54, 150))
        rotated = card.rotate(angle, Image.Resampling.BICUBIC, expand=True)
        board.alpha_composite(rotated, (x1, y1))
        center = ((x1 + x2) // 2, (y1 + y2) // 2)
        centers.append(center)

    for start, end in zip(centers, centers[1:]):
        draw.line((*start, *end), fill=(176, 38, 43, 230), width=7)
    draw.line((*centers[0], *centers[-1]), fill=(176, 38, 43, 190), width=6)
    for x, y in centers:
        draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill=(225, 169, 64, 255), outline=(70, 32, 20, 255), width=3)
    return Image.alpha_composite(background, board).convert("RGB")
