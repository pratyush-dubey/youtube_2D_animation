"""
Stability AI image provider — credits-based REST API.
https://platform.stability.ai
Requires STABILITY_API_KEY in .env
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path


class StabilityProvider:
    """Generate images using the Stability AI REST API."""

    def generate(self, prompt: str, output_path: Path) -> Path:
        from app.config.settings import settings
        api_key = settings.stability_api_key
        if not api_key:
            raise ValueError(
                "STABILITY_API_KEY not set. "
                "Get a key from https://platform.stability.ai"
            )
        payload = json.dumps({
            "prompt": prompt[:1000],
            "aspect_ratio": "16:9",
            "output_format": "jpeg",
        }).encode()
        req = urllib.request.Request(
            "https://api.stability.ai/v2beta/stable-image/generate/core",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "image/*",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        return output_path
