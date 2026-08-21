"""
Pollinations AI image provider — free, no API key required.
https://pollinations.ai
"""
from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path


class PollinationsProvider:
    """Generate images using the Pollinations AI free API."""

    def generate(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        from app.config.settings import settings
        w = settings.image_width
        h = settings.image_height
        # enhance=false: prevent Pollinations from rewriting the prompt with its
        # own LLM, which replaces specific subjects with generic imagery.
        safe = urllib.parse.quote(prompt[:800])
        url = (
            f"https://image.pollinations.ai/prompt/{safe}"
            f"?width={w}&height={h}&model=flux&nologo=true&enhance=false&seed={seed}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "AIYouTubeBot/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) < 500:
            raise ValueError("Pollinations returned empty or tiny image")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        return output_path
