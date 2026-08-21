"""
Gemini Imagen image provider.

Uses Google's Imagen 3 model via the google-genai SDK (same SDK already
used for text generation).  No extra dependency required — just the same
GEMINI_API_KEY that drives the LLM.

Model: imagen-3.0-generate-002
  - 1:1 / 3:4 / 4:3 / 9:16 / 16:9 aspect ratios supported
  - Free quota: ~1 image / request on the free tier
  - Returns base64-encoded PNG/JPEG bytes

Requires google-genai >= 1.0  (pip install google-genai)
"""
from __future__ import annotations

import base64
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Imagen 3 model name
_IMAGEN_MODEL = "imagen-3.0-generate-002"


class GeminiImagenProvider:
    """Generate images using Google Gemini Imagen 3."""

    def __init__(self, api_key: str | None = None) -> None:
        from app.config.settings import settings
        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            raise ValueError(
                "Gemini API key not set. "
                "Add GEMINI_API_KEY to your .env file."
            )

    def generate(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        """
        Generate a 1920×1080 image from prompt and save to output_path.

        Falls back gracefully: if Imagen quota is exceeded or the model
        refuses the prompt, raises an exception so AssetAgent can try the
        next provider.
        """
        try:
            from google import genai
            from google.genai import types as gtypes
        except ImportError:
            raise ImportError(
                "google-genai SDK not installed. Run: pip install google-genai"
            )

        client = genai.Client(api_key=self.api_key)

        # Imagen 3 supports 16:9 natively — closest to 1920×1080
        response = client.models.generate_images(
            model=_IMAGEN_MODEL,
            prompt=prompt[:2000],
            config=gtypes.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9",
                # safety_filter_level: block only high-severity content
                safety_filter_level="block_only_high",
                person_generation="allow_adult",
            ),
        )

        if not response.generated_images:
            raise RuntimeError("Imagen returned no images")

        img_data = response.generated_images[0]
        # The SDK returns an Image object with .image.image_bytes
        raw_bytes = img_data.image.image_bytes

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Resize / convert to JPEG 1920×1080 via Pillow if available
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            img = img.resize((1920, 1080), Image.LANCZOS)
            img.save(str(output_path), "JPEG", quality=92)
        except ImportError:
            # Pillow not available — write raw bytes as-is
            output_path.write_bytes(raw_bytes)

        logger.info(
            "imagen_generated",
            path=str(output_path),
            prompt_len=len(prompt),
        )
        return output_path
