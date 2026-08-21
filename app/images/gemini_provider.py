"""
Gemini native image provider.

Uses Google's current native image model via the google-genai SDK (same SDK already
used for text generation).  No extra dependency required — just the same
GEMINI_API_KEY that drives the LLM.

The model name is configured with GEMINI_IMAGE_MODEL. Generated frames are
center-cropped to the pipeline's 1920x1080 canvas.

Requires google-genai >= 1.0  (pip install google-genai)
"""
from __future__ import annotations

import io
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

class GeminiImagenProvider:
    """Generate images using Google's configured native image model."""

    def __init__(self, api_key: str | None = None) -> None:
        from app.config.settings import settings
        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            raise ValueError(
                "Gemini API key not set. "
                "Add GEMINI_API_KEY to your .env file."
            )

    def generate(
        self, prompt: str, output_path: Path, seed: int = 42,
        reference_images: list[Path] | None = None,
    ) -> Path:
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
        from app.config.settings import settings

        contents = [gtypes.Part.from_text(text=prompt[:4000])]
        for reference in reference_images or []:
            if reference.exists():
                mime = "image/png" if reference.suffix.lower() == ".png" else "image/jpeg"
                contents.append(
                    gtypes.Part.from_bytes(data=reference.read_bytes(), mime_type=mime)
                )
        if reference_images:
            contents[0] = gtypes.Part.from_text(
                text=(
                    prompt[:3300]
                    + " Use the supplied portrait strictly as the identity reference. "
                    "Preserve the same facial geometry, age, skin tone, hairline, and "
                    "distinguishing features. Do not substitute or blend another face."
                )
            )

        response = client.models.generate_content(
            model=settings.gemini_image_model,
            contents=contents,
            config=gtypes.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        parts = getattr(response, "parts", None) or []
        raw_bytes = next(
            (
                part.inline_data.data
                for part in parts
                if getattr(part, "inline_data", None)
                and getattr(part.inline_data, "data", None)
            ),
            None,
        )
        if not raw_bytes:
            raise RuntimeError("Gemini image model returned no image bytes")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Resize / convert to JPEG 1920×1080 via Pillow if available
        try:
            from PIL import Image, ImageOps
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            img = ImageOps.fit(
                img, (1920, 1080), method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
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
