"""
Placeholder image provider — instant, no API, no internet.
Generates coloured gradient frames using Pillow.
Always works as a fallback.
"""
from __future__ import annotations

from pathlib import Path


_PALETTE = [
    "#1a1a2e", "#16213e", "#0f3460", "#533483",
    "#2d6a4f", "#1b4332", "#264653", "#2a9d8f",
]


class PlaceholderProvider:
    """Generate placeholder JPEG images locally using Pillow."""

    def generate(self, prompt: str, output_path: Path) -> Path:
        from app.config.settings import settings
        try:
            from PIL import Image, ImageDraw, ImageFont
            scene_id = hash(prompt) % len(_PALETTE)
            bg = _PALETTE[scene_id]
            r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            img = Image.new("RGB", (settings.image_width, settings.image_height), (r, g, b))
            draw = ImageDraw.Draw(img)
            draw.text((80, 80), prompt[:100], fill=(220, 220, 220))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(output_path), "JPEG", quality=85)
        except ImportError:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 2000)
        return output_path
