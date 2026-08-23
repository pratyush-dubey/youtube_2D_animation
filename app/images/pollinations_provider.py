"""
Pollinations AI image provider — free, no API key required.
https://pollinations.ai
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class PollinationsProvider:
    """Generate images using the Pollinations AI free API."""

    def generate(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        from app.config.settings import settings
        return self._request(prompt, output_path, settings.image_width, settings.image_height, seed, model="flux")

    def generate_image_to_image(
        self, prompt: str, image_url: str, output_path: Path,
        width: int = 1024, height: int = 1536, seed: int = 42,
    ) -> Path:
        """Reference-guided generation via the `kontext` model.

        `image_url` must be a publicly fetchable HTTP(S) URL (Pollinations
        fetches it server-side); a local file path cannot be passed directly.
        """
        return self._request(prompt, output_path, width, height, seed, model="kontext", image_url=image_url)

    def generate_portrait(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        """Full-body character art needs a tall frame, not the 16:9 scene default."""
        return self._request(prompt, output_path, 1024, 1536, seed, model="flux")

    def _request(
        self, prompt: str, output_path: Path, width: int, height: int, seed: int,
        *, model: str, image_url: str | None = None,
    ) -> Path:
        # enhance=false: prevent Pollinations from rewriting the prompt with its
        # own LLM, which replaces specific subjects with generic imagery.
        safe = urllib.parse.quote(prompt[:800])
        url = (
            f"https://image.pollinations.ai/prompt/{safe}"
            f"?width={width}&height={height}&model={model}&nologo=true&enhance=false&seed={seed}"
        )
        if image_url:
            url += f"&image={urllib.parse.quote(image_url, safe='')}"
        req = urllib.request.Request(url, headers={"User-Agent": "AIYouTubeBot/1.0"})
        # The free endpoint occasionally 500s under load (transient, not a
        # rejection of this request) - a couple of quick retries clears most
        # of them instead of burning the whole attempt (e.g. dropping a
        # kontext identity-conditioned generation straight to a text-only
        # fallback for what was really just a momentary server hiccup).
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = resp.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == max_attempts - 1:
                    raise
                time.sleep(2 * (attempt + 1))
        if len(data) < 500:
            raise ValueError("Pollinations returned empty or tiny image")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        return output_path
