"""True layered 2.5D frame composition with per-layer parallax."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.cinematic.layers import LayerAsset


class ParallaxCompositor:
    def __init__(self, width=1920, height=1080, debug=False) -> None:
        self.width, self.height, self.debug = width, height, debug

    def frame(self, layers: list[LayerAsset], progress: float, camera_strength: float,
              shot_id: str, lighting=1.0, fog=0.0) -> Image.Image:
        canvas = Image.new("RGBA", (self.width, self.height), (5, 8, 12, 255))
        camera_curve = progress * progress * (3 - 2 * progress)
        for layer in sorted(layers, key=lambda item: item.z_index):
            source = Image.open(layer.path).convert("RGBA")
            overscan = 1.0 + camera_strength * 0.16 * max(0.15, layer.parallax_speed)
            size = (round(self.width * overscan), round(self.height * overscan))
            fitted = ImageOps.fit(source, size, Image.Resampling.LANCZOS)
            travel = camera_strength * 150 * layer.parallax_speed
            x = round((self.width - fitted.width) / 2 - (camera_curve - 0.5) * travel)
            y = round((self.height - fitted.height) / 2 + math.sin(progress * math.pi) * 5 * layer.depth)
            canvas.alpha_composite(fitted, (x, y))
            if self.debug:
                draw = ImageDraw.Draw(canvas)
                draw.rectangle((max(0, x), max(0, y), min(self.width - 1, x + fitted.width), min(self.height - 1, y + fitted.height)), outline=(255, 180, 40, 150), width=2)
                draw.text((max(8, x + 8), max(8, y + 8)), f"{layer.layer_id} d={layer.depth:.2f} p={layer.parallax_speed:.2f}", fill=(255, 230, 170, 230))
        if lighting != 1.0:
            canvas = ImageEnhance.Brightness(canvas).enhance(lighting)
        if fog > 0:
            haze = Image.new("RGBA", canvas.size, (180, 195, 190, round(70 * fog)))
            canvas = Image.alpha_composite(canvas, haze.filter(ImageFilter.GaussianBlur(2)))
        if self.debug:
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((16, 16, 440, 68), fill=(0, 0, 0, 170))
            draw.text((30, 28), f"2d25d_debug | {shot_id} | camera={camera_strength:.2f}", fill="white")
        return canvas.convert("RGB")
