"""
Image generation module.

Provides an ImageProvider abstraction so callers never depend on a specific
image service.  The AssetAgent uses this internally.

Usage:
    from app.images.generator import get_image_provider
    provider = get_image_provider()           # uses settings.image_provider
    path = provider.generate(prompt, output_path)
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ImageProvider(Protocol):
    """Abstract image provider interface."""

    def generate(self, prompt: str, output_path: Path) -> Path:
        """Generate an image from a text prompt and save it to output_path."""
        ...


def get_image_provider(override: str | None = None) -> ImageProvider:
    """
    Return the configured image provider instance.

    Provider selection (in priority order):
      1. ``override`` argument (for testing / one-off use)
      2. ``IMAGE_PROVIDER`` env var / settings.image_provider
      3. Falls back to placeholder (always available, no API needed)
    """
    from app.config.settings import settings
    name = (override or settings.image_provider).lower()

    if name in ("pollinations",):
        from app.images.pollinations_provider import PollinationsProvider
        return PollinationsProvider()

    if name in ("stability", "stable_diffusion"):
        from app.images.stability_provider import StabilityProvider
        return StabilityProvider()

    # placeholder — always available
    from app.images.placeholder_provider import PlaceholderProvider
    return PlaceholderProvider()


from app.images.provider_interface import (
    ProductionImageProvider,
    ProviderCapabilities,
    get_production_image_provider,
)

__all__ = [
    "ImageProvider", "get_image_provider", "ProductionImageProvider",
    "ProviderCapabilities", "get_production_image_provider",
]
