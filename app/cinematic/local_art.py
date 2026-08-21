"""Create original layered artwork for the zero-cost 10-second bank proof.

This is an intentionally small, deterministic art generator, not a placeholder
fallback.  It produces separate transparent production layers and an articulated
character kit so Blender receives editable assets even when no cloud image API
is configured.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


SIZE = (1280, 720)
INK = (40, 31, 27, 255)
CREAM = (225, 206, 166, 255)
TEAL = (46, 91, 91, 255)
UMBER = (105, 64, 42, 255)


def generate_bank_proof_art(output_dir: Path) -> dict:
    """Generate a coherent layer pack and return its manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    layers = output_dir / "layers"
    parts = output_dir / "character_parts"
    layers.mkdir(exist_ok=True)
    parts.mkdir(exist_ok=True)

    generated = {
        "exterior_background": _exterior_background(layers / "exterior_background.png"),
        "exterior_far": _exterior_far(layers / "exterior_far.png"),
        "exterior_bank": _exterior_bank(layers / "exterior_bank.png"),
        "exterior_foreground": _exterior_foreground(layers / "exterior_foreground.png"),
        "interior_background": _interior_background(layers / "interior_background.png"),
        "interior_midground": _interior_midground(layers / "interior_midground.png"),
        "interior_foreground": _interior_foreground(layers / "interior_foreground.png"),
    }
    generated.update({f"part_{name}": path for name, path in _character_parts(parts).items()})
    manifest = {
        "generator": "local_original_layered_illustration_v1",
        "license": "project-authored",
        "cost_inr": 0,
        "canvas": list(SIZE),
        "character": {
            "id": "fictional_indian_adult_01",
            "description": "fictional adult Indian bank employee; moustache, side-parted black hair, cream shirt, teal trousers",
        },
        "assets": {name: str(path.resolve()) for name, path in generated.items()},
        "depths": {
            "background": -10, "far_midground": -7, "midground": -4,
            "character": 0, "foreground": 4, "near_foreground": 8,
        },
    }
    manifest_path = output_dir / "asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _canvas() -> Image.Image:
    return Image.new("RGBA", SIZE, (0, 0, 0, 0))


def _save(image: Image.Image, path: Path) -> Path:
    image.save(path, "PNG")
    return path


def _paper_texture(image: Image.Image, amount: int = 16) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(0, SIZE[1], 9):
        alpha = 4 + (y * 13 % max(amount, 1))
        draw.line((0, y, SIZE[0], y), fill=(68, 43, 31, alpha), width=1)


def _exterior_background(path: Path) -> Path:
    image = Image.new("RGBA", SIZE, (167, 177, 164, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(SIZE[1]):
        t = y / SIZE[1]
        draw.line((0, y, SIZE[0], y), fill=(152 + int(44*t), 169 + int(23*t), 165 - int(31*t), 255))
    draw.ellipse((850, 65, 1015, 230), fill=(255, 218, 151, 90))
    _paper_texture(image)
    return _save(image, path)


def _exterior_far(path: Path) -> Path:
    image = _canvas(); draw = ImageDraw.Draw(image, "RGBA")
    palette = [(85, 93, 86, 180), (104, 101, 84, 185), (69, 82, 79, 175)]
    for i, x in enumerate(range(-40, 1340, 135)):
        h = 110 + (i * 37 % 120)
        draw.rectangle((x, 445-h, x+115, 445), fill=palette[i % len(palette)])
        for wx in range(x+14, x+105, 28):
            for wy in range(455-h, 432, 32):
                draw.rectangle((wx, wy, wx+10, wy+14), fill=(214, 193, 143, 85))
    draw.rectangle((0, 442, 1280, 510), fill=(74, 91, 76, 210))
    return _save(image.filter(ImageFilter.GaussianBlur(0.6)), path)


def _exterior_bank(path: Path) -> Path:
    image = _canvas(); draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((250, 172, 1110, 626), fill=(196, 168, 119, 255), outline=INK, width=8)
    draw.polygon([(215, 180), (680, 83), (1147, 180)], fill=(88, 55, 38, 255), outline=INK)
    draw.rectangle((315, 233, 1045, 316), fill=(48, 78, 74, 255), outline=INK, width=6)
    draw.text((470, 250), "BENGALURU MERCANTILE BANK", fill=(235, 218, 169, 255), stroke_width=1, stroke_fill=INK)
    for x in (330, 930):
        draw.rectangle((x, 353, x+120, 540), fill=(57, 83, 80, 255), outline=INK, width=6)
        draw.line((x+60, 353, x+60, 540), fill=(210, 191, 145, 180), width=4)
    draw.rectangle((570, 342, 790, 626), fill=(37, 52, 49, 255), outline=INK, width=7)
    draw.polygon([(590, 360), (680, 348), (680, 620), (590, 614)], fill=(86, 119, 109, 230), outline=INK)
    draw.rectangle((0, 626, 1280, 720), fill=(115, 89, 65, 255))
    for y in (646, 684): draw.line((0, y, 1280, y-12), fill=(72, 59, 47, 130), width=3)
    _paper_texture(image, 8)
    return _save(image, path)


def _exterior_foreground(path: Path) -> Path:
    image = _canvas(); draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((34, 145, 66, 720), fill=(42, 43, 38, 255))
    draw.ellipse((9, 112, 91, 183), fill=(52, 60, 53, 255), outline=(22, 23, 20, 255), width=5)
    draw.polygon([(1020, 720), (1280, 720), (1280, 360), (1210, 390), (1162, 520)], fill=(27, 37, 31, 240))
    draw.ellipse((1055, 330, 1325, 585), fill=(43, 74, 53, 230))
    return _save(image.filter(ImageFilter.GaussianBlur(0.35)), path)


def _interior_background(path: Path) -> Path:
    image = Image.new("RGBA", SIZE, (174, 141, 94, 255)); draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, 1280, 110), fill=(83, 65, 45, 255))
    draw.rectangle((0, 585, 1280, 720), fill=(75, 57, 42, 255))
    for x in range(0, 1280, 95): draw.line((x, 585, x+60, 720), fill=(115, 83, 53, 120), width=3)
    for y in range(610, 720, 35): draw.line((0, y, 1280, y), fill=(48, 39, 33, 100), width=2)
    for x in (120, 865):
        draw.rectangle((x, 165, x+250, 400), fill=(52, 74, 67, 255), outline=INK, width=8)
        draw.line((x+125, 165, x+125, 400), fill=CREAM, width=4)
    draw.rectangle((482, 188, 798, 340), fill=(207, 190, 146, 255), outline=INK, width=7)
    draw.text((550, 245), "ACCOUNTS", fill=INK)
    _paper_texture(image)
    return _save(image, path)


def _interior_midground(path: Path) -> Path:
    image = _canvas(); draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((120, 425, 1120, 570), fill=(95, 57, 37, 255), outline=INK, width=8)
    draw.rectangle((142, 450, 1098, 486), fill=(182, 137, 79, 255), outline=INK, width=4)
    for x in (220, 520, 820):
        draw.rectangle((x, 486, x+22, 650), fill=(57, 40, 31, 255))
        draw.rectangle((x+190, 486, x+212, 650), fill=(57, 40, 31, 255))
    draw.rectangle((845, 364, 1015, 426), fill=(225, 209, 170, 255), outline=INK, width=4)
    draw.line((870, 382, 990, 382), fill=(89, 71, 50, 180), width=3)
    draw.line((870, 397, 970, 397), fill=(89, 71, 50, 150), width=3)
    return _save(image, path)


def _interior_foreground(path: Path) -> Path:
    image = _canvas(); draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, 82, 720), fill=(36, 31, 26, 255))
    draw.rectangle((1190, 0, 1280, 720), fill=(36, 31, 26, 255))
    draw.rectangle((0, 0, 1280, 45), fill=(34, 29, 25, 255))
    draw.polygon([(0, 720), (245, 720), (170, 540), (0, 485)], fill=(26, 25, 22, 245))
    return _save(image, path)


def _character_parts(directory: Path) -> dict[str, Path]:
    specs = {
        "torso": ((180, 235), "torso"), "head": ((132, 150), "head"),
        "upper_arm_left": ((56, 142), "sleeve"), "lower_arm_left": ((46, 126), "skin"),
        "hand_left": ((42, 55), "hand"), "upper_arm_right": ((56, 142), "sleeve"),
        "lower_arm_right": ((46, 126), "skin"), "hand_right": ((42, 55), "hand"),
        "upper_leg_left": ((68, 166), "trouser"), "lower_leg_left": ((60, 160), "trouser"),
        "foot_left": ((92, 48), "shoe"), "upper_leg_right": ((68, 166), "trouser"),
        "lower_leg_right": ((60, 160), "trouser"), "foot_right": ((92, 48), "shoe"),
        "eyes": ((82, 28), "eyes"), "eyebrows": ((88, 24), "eyebrows"),
        "mouth": ((55, 30), "mouth"), "neck": ((50, 50), "skin"),
    }
    result = {}
    for name, (size, kind) in specs.items():
        scale = 3
        image = Image.new("RGBA", (size[0]*scale, size[1]*scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image, "RGBA"); w, h = image.size; pad = 5*scale
        if kind == "torso":
            draw.polygon([(w*.18, h*.05), (w*.82, h*.05), (w*.94, h*.96), (w*.06, h*.96)], fill=(218, 202, 161, 255), outline=INK, width=9)
            draw.line((w*.5, h*.12, w*.5, h*.91), fill=(117, 91, 61, 170), width=5)
            for y in (.27, .48, .69): draw.ellipse((w*.47, h*y, w*.53, h*y+w*.06), fill=INK)
        elif kind == "head":
            draw.ellipse((pad, pad, w-pad, h-pad), fill=(154, 103, 69, 255), outline=INK, width=9)
            draw.pieslice((pad-3, 0, w-pad+3, h*.68), 180, 360, fill=(35, 29, 25, 255))
            draw.arc((w*.18, h*.47, w*.82, h*.88), 205, 335, fill=(39, 29, 25, 255), width=9)
            draw.polygon([(w*.48, h*.48), (w*.43, h*.67), (w*.55, h*.66)], fill=(119, 75, 52, 255))
        elif kind in {"sleeve", "skin", "trouser"}:
            color = (216, 198, 157, 255) if kind == "sleeve" else ((154, 103, 69, 255) if kind == "skin" else (41, 82, 82, 255))
            draw.rounded_rectangle((pad, 0, w-pad, h-pad), radius=w//3, fill=color, outline=INK, width=8)
        elif kind == "hand": draw.ellipse((pad, 0, w-pad, h-pad), fill=(154, 103, 69, 255), outline=INK, width=7)
        elif kind == "shoe": draw.rounded_rectangle((3, pad, w-3, h-pad), radius=h//3, fill=(43, 33, 29, 255), outline=INK, width=7)
        elif kind == "eyes":
            for x in (.28, .72):
                draw.ellipse((w*x-20, h*.2, w*x+20, h*.82), fill=(236, 224, 194, 255), outline=INK, width=5)
                draw.ellipse((w*x-6, h*.36, w*x+8, h*.74), fill=(30, 25, 22, 255))
        elif kind == "eyebrows":
            draw.line((w*.08, h*.72, w*.4, h*.48), fill=INK, width=10); draw.line((w*.6, h*.48, w*.92, h*.72), fill=INK, width=10)
        elif kind == "mouth": draw.arc((w*.14, h*.05, w*.86, h*.72), 12, 168, fill=(67, 36, 32, 255), width=9)
        path = directory / f"{name}.png"; image.save(path); result[name] = path
    return result
