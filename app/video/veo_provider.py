"""Google Veo 3 video-generation provider.

Animates a single still image (or a text prompt alone) into a short clip via
the Gemini API's video-generation endpoint. This is a distinct capability
from GeminiImagenProvider (app/images/gemini_provider.py, still images only).

Verified against the installed google-genai==2.20.0 SDK.  That version does
provide ``GenerateVideosSource``; the older direct ``prompt=``/``image=``
arguments remain accepted but are deprecated by the current SDK.

Cost note: Veo billing is real and non-trivial (roughly $0.05-$0.60 per
second of generated video depending on model tier/resolution as of 2026;
verify current pricing before running this in volume) - this provider makes
no attempt to hide that from the caller; callers should treat every call as
a real charge.
"""
from __future__ import annotations

import time
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Veo 3.1 tiers, cheapest first. Fast/Lite trade quality for cost; Standard
# is the highest quality generally available via the API as of this writing.
MODEL_LITE = "veo-3.1-lite-generate-preview"
MODEL_FAST = "veo-3.1-fast-generate-preview"
MODEL_STANDARD = "veo-3.1-generate-preview"

_POLL_INTERVAL_SECONDS = 10
_MAX_POLL_SECONDS = 20 * 60  # a single Veo generation can legitimately take several minutes


class VeoGenerationError(RuntimeError):
    pass


class VeoVideoProvider:
    """Animate a still image (or a bare prompt) into a short Veo clip."""

    def __init__(self, api_key: str | None = None, model: str = MODEL_FAST) -> None:
        from app.config.settings import settings

        self.api_key = api_key or settings.gemini_api_key
        if not self.api_key:
            raise ValueError("Gemini API key not set. Add GEMINI_API_KEY to your .env file.")
        self.model = model

    def _client(self):
        from google import genai

        return genai.Client(http_options={"api_version": "v1beta"}, api_key=self.api_key)

    def generate_from_image(
        self,
        prompt: str,
        image_path: Path,
        output_path: Path,
        *,
        duration_seconds: int = 8,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        generate_audio: bool = False,
        person_generation: str = "allow_adult",
        negative_prompt: str | None = None,
        seed: int | None = None,
    ) -> Path:
        """Animate `image_path` according to `prompt`, saving the result to
        `output_path`. This is the primary entry point for the
        "generate a still with Nano Banana, then animate it" workflow -
        `image_path` should be that still.
        """
        from google.genai import types

        if not image_path.is_file():
            raise FileNotFoundError(f"Source image does not exist: {image_path}")
        mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        source_image = types.Image(image_bytes=image_path.read_bytes(), mime_type=mime_type)
        return self._generate(
            prompt=prompt, image=source_image, output_path=output_path,
            duration_seconds=duration_seconds, aspect_ratio=aspect_ratio,
            resolution=resolution, generate_audio=generate_audio,
            person_generation=person_generation, negative_prompt=negative_prompt, seed=seed,
        )

    def generate_from_text(
        self,
        prompt: str,
        output_path: Path,
        *,
        duration_seconds: int = 8,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        generate_audio: bool = False,
        person_generation: str = "allow_adult",
        negative_prompt: str | None = None,
        seed: int | None = None,
    ) -> Path:
        """Text-only generation, no source image. Prefer generate_from_image
        for this project's actual workflow - a bare-prompt Veo call has no
        identity/composition anchor, so it can invent a different scene or
        person entirely rather than animating what was already approved.
        """
        return self._generate(
            prompt=prompt, image=None, output_path=output_path,
            duration_seconds=duration_seconds, aspect_ratio=aspect_ratio,
            resolution=resolution, generate_audio=generate_audio,
            person_generation=person_generation, negative_prompt=negative_prompt, seed=seed,
        )

    def _generate(
        self, *, prompt: str, image, output_path: Path,
        duration_seconds: int, aspect_ratio: str, resolution: str,
        generate_audio: bool, person_generation: str,
        negative_prompt: str | None, seed: int | None,
    ) -> Path:
        from google.genai import types
        from app.config.settings import settings

        if duration_seconds not in {4, 6, 8}:
            raise ValueError(f"Veo 3.1 duration_seconds must be 4, 6, or 8; got {duration_seconds}")

        client = self._client()
        config = types.GenerateVideosConfig(
            number_of_videos=1,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            person_generation=person_generation,
            generate_audio=generate_audio,
            negative_prompt=negative_prompt,
            seed=seed,
            fps=24,
            enhance_prompt=settings.veo_enhance_prompt,
        )
        logger.info(
            "veo_generation_started", model=self.model, duration_seconds=duration_seconds,
            resolution=resolution, has_image=image is not None,
        )
        started = time.monotonic()
        source = types.GenerateVideosSource(prompt=prompt, image=image)
        operation = client.models.generate_videos(model=self.model, source=source, config=config)

        while not operation.done:
            if time.monotonic() - started > _MAX_POLL_SECONDS:
                raise VeoGenerationError(
                    f"Veo generation did not complete within {_MAX_POLL_SECONDS}s"
                )
            time.sleep(_POLL_INTERVAL_SECONDS)
            operation = client.operations.get(operation)

        if operation.error:
            raise VeoGenerationError(f"Veo generation failed: {operation.error}")

        result = operation.result
        if not result or not result.generated_videos:
            raise VeoGenerationError("Veo returned no generated videos")
        if result.rai_media_filtered_count:
            raise VeoGenerationError(
                f"Veo filtered the output for policy reasons: {result.rai_media_filtered_reasons}"
            )

        generated = result.generated_videos[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        client.files.download(file=generated.video)
        generated.video.save(str(output_path))

        elapsed = round(time.monotonic() - started, 1)
        logger.info("veo_generation_complete", path=str(output_path), elapsed_seconds=elapsed)
        return output_path
