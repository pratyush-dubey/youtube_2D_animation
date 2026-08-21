"""Consistent procedural 2D character sprites and FFmpeg motion expressions."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


CHARACTER_MOTIONS = {
    "idle-breathe",
    "walk-in-left",
    "walk-in-right",
    "walk-across",
    "slow-drift",
    "reveal",
}


def create_character_sprite(
    output_dir: Path, character_name: str, visual: str = "",
    reference_path: Path | None = None,
) -> Path:
    """Create one reusable transparent cutout for a recurring character."""
    reference_key = ""
    if reference_path and reference_path.exists():
        stat = reference_path.stat()
        reference_key = f"{reference_path}|{stat.st_size}|{stat.st_mtime_ns}"
    identity = f"{character_name}|{visual}|{reference_key}".encode("utf-8")
    digest = hashlib.sha256(identity).digest()
    slug = hashlib.sha256(identity + b"|sprite-v2").hexdigest()[:12]
    path = output_dir / "characters" / f"{slug}.png"
    if path.exists() and path.stat().st_size > 1000:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    if reference_path and reference_path.exists():
        return _create_reference_sprite(reference_path, path)

    scale = 2
    canvas = Image.new("RGBA", (520 * scale, 980 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    palettes = [
        ((33, 67, 57), (194, 139, 70)),
        ((43, 50, 63), (170, 47, 50)),
        ((67, 49, 39), (200, 150, 72)),
        ((31, 58, 75), (180, 54, 49)),
    ]
    coat, accent = palettes[digest[0] % len(palettes)]
    lower = visual.lower()
    if "forest-green" in lower or "forest green" in lower or "green coat" in lower:
        coat = (31, 67, 55)
    elif "crimson" in lower or "red coat" in lower:
        coat = (124, 35, 40)
    elif "amber" in lower or "ochre" in lower:
        coat = (137, 91, 36)
    elif "black" in lower:
        coat = (26, 29, 29)
    skin = [(111, 73, 52), (151, 103, 72), (190, 139, 98), (222, 174, 126)][digest[1] % 4]
    hair = [(18, 17, 16), (39, 27, 20), (62, 42, 29)][digest[2] % 3]

    def pts(values):
        return [(x * scale, y * scale) for x, y in values]

    # Soft grounding shadow.
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((105 * scale, 914 * scale, 430 * scale, 972 * scale), fill=(0, 0, 0, 145))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16 * scale))
    canvas = Image.alpha_composite(canvas, shadow)
    draw = ImageDraw.Draw(canvas)

    # Back leg and arm create an asymmetric readable pose.
    draw.polygon(pts([(245, 670), (330, 675), (355, 925), (292, 930)]), fill=(*_shade(coat, 0.55), 255))
    draw.polygon(pts([(205, 670), (278, 672), (230, 930), (166, 928)]), fill=(*_shade(coat, 0.7), 255))
    draw.rounded_rectangle((151 * scale, 900 * scale, 255 * scale, 950 * scale), radius=16 * scale, fill=(20, 24, 24, 255))
    draw.rounded_rectangle((285 * scale, 900 * scale, 402 * scale, 950 * scale), radius=16 * scale, fill=(20, 24, 24, 255))
    draw.polygon(pts([(175, 345), (120, 405), (105, 665), (171, 675), (215, 455)]), fill=(*_shade(coat, 0.65), 255))
    draw.ellipse((91 * scale, 642 * scale, 160 * scale, 715 * scale), fill=(*skin, 255))

    # Torso / coat with a small accent seam gives a reusable 2D rig appearance.
    draw.polygon(pts([(180, 325), (330, 325), (390, 690), (125, 690)]), fill=(*coat, 255))
    draw.line(pts([(257, 350), (258, 671)]), fill=(*accent, 210), width=5 * scale)
    draw.polygon(pts([(326, 355), (384, 410), (420, 616), (362, 632), (292, 450)]), fill=(*_shade(coat, 0.78), 255))
    draw.ellipse((373 * scale, 588 * scale, 441 * scale, 660 * scale), fill=(*skin, 255))

    # Neck, head, ear, hair, and restrained face marks.
    draw.rectangle((226 * scale, 265 * scale, 290 * scale, 350 * scale), fill=(*skin, 255))
    draw.ellipse((178 * scale, 100 * scale, 340 * scale, 300 * scale), fill=(*skin, 255))
    draw.ellipse((319 * scale, 180 * scale, 350 * scale, 229 * scale), fill=(*_shade(skin, 0.9), 255))
    if digest[3] % 2:
        draw.pieslice((166 * scale, 70 * scale, 349 * scale, 270 * scale), 178, 354, fill=(*hair, 255))
        draw.polygon(pts([(175, 155), (192, 87), (305, 75), (342, 160), (300, 125), (230, 143)]), fill=(*hair, 255))
    else:
        draw.pieslice((168 * scale, 65 * scale, 348 * scale, 270 * scale), 175, 358, fill=(*hair, 255))
        draw.ellipse((154 * scale, 100 * scale, 220 * scale, 280 * scale), fill=(*hair, 255))
    draw.line((272 * scale, 184 * scale, 300 * scale, 182 * scale), fill=(28, 25, 22, 220), width=4 * scale)
    draw.line((292 * scale, 225 * scale, 307 * scale, 230 * scale), fill=(78, 43, 35, 180), width=3 * scale)

    # Directional shadow ties the cutout to low-key documentary lighting.
    alpha = canvas.getchannel("A")
    shade = Image.new("RGBA", canvas.size, (3, 10, 8, 0))
    shade_alpha = Image.new("L", canvas.size, 0)
    shade_draw = ImageDraw.Draw(shade_alpha)
    shade_draw.rectangle((285 * scale, 50 * scale, 520 * scale, 950 * scale), fill=82)
    shade_alpha = Image.composite(shade_alpha, Image.new("L", canvas.size, 0), alpha)
    shade.putalpha(shade_alpha.filter(ImageFilter.GaussianBlur(12 * scale)))
    canvas = Image.alpha_composite(canvas, shade)

    canvas = canvas.resize((520, 980), Image.Resampling.LANCZOS)
    canvas.save(path, "PNG", optimize=True)
    return path


def _create_reference_sprite(reference_path: Path, output_path: Path) -> Path:
    """Create a moving archival portrait cutout without fabricating a face."""
    from PIL import ImageEnhance, ImageOps

    source = Image.open(reference_path).convert("RGB")
    portrait = ImageOps.fit(
        source, (430, 760), method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.32),
    )
    portrait = ImageEnhance.Color(portrait).enhance(0.62)
    portrait = ImageEnhance.Contrast(portrait).enhance(1.08)
    canvas = Image.new("RGBA", (520, 900), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((47, 48, 497, 838), 12, fill=(0, 0, 0, 165))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas, shadow)
    card = Image.new("RGBA", (466, 806), (218, 209, 185, 255))
    card.alpha_composite(portrait.convert("RGBA"), (18, 18))
    ImageDraw.Draw(card).rectangle((34, 789, 360, 797), fill=(63, 59, 49, 145))
    canvas.alpha_composite(card.rotate(-1.5, Image.Resampling.BICUBIC, expand=True), (18, 34))
    canvas.save(output_path, "PNG", optimize=True)
    return output_path


def character_overlay_expression(
    motion: str, position: str, duration: float
) -> tuple[str, str]:
    """Return animated FFmpeg overlay x/y expressions."""
    motion = motion if motion in CHARACTER_MOTIONS else "idle-breathe"
    target = {"left": "main_w*0.10", "center": "main_w*0.39", "right": "main_w*0.70"}.get(
        position, "main_w*0.70"
    )
    bob = "main_h-overlay_h-18+7*sin(2*PI*t/0.72)"
    if motion == "walk-in-left":
        x = f"min({target},-overlay_w+t*({target}+overlay_w)/1.25)"
        return x, bob
    if motion == "walk-in-right":
        x = f"max({target},main_w-t*(main_w-{target})/1.25)"
        return x, bob
    if motion == "walk-across":
        return f"-overlay_w+t*(main_w+overlay_w)/{max(duration, 0.1):.3f}", bob
    if motion == "slow-drift":
        return f"{target}+24*sin(2*PI*t/3.2)", "main_h-overlay_h-18+4*sin(2*PI*t/1.8)"
    if motion == "reveal":
        return f"max({target},main_w-t*(main_w-{target})/2.0)", "main_h-overlay_h-18"
    return f"{target}+3*sin(2*PI*t/2.6)", "main_h-overlay_h-18+4*sin(2*PI*t/1.5)"


def character_visual(character_sheet: dict, character_name: str) -> str:
    for character in character_sheet.get("characters", []):
        if str(character.get("name", "")).lower() == character_name.lower():
            return str(character.get("visual", ""))
    return ""


def character_reference(character_sheet: dict, character_name: str) -> Path | None:
    for character in character_sheet.get("characters", []):
        if str(character.get("name", "")).casefold() != character_name.casefold():
            continue
        if not str(character.get("identity_reference_status", "")).startswith("verified"):
            return None
        path = Path(str(character.get("reference_image", "")))
        return path if path.exists() else None
    return None


def _shade(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(channel * amount))) for channel in color)
