"""Capability-aware provider interface for illustrated production assets."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderCapabilities:
    reference_images: bool = False
    native_transparency: bool = False
    deterministic_seed: bool = False
    image_to_image: bool = False


class ProductionImageProvider:
    """Adds production asset operations without inventing provider features."""

    def __init__(self, name: str, provider: Any, capabilities: ProviderCapabilities) -> None:
        self.name = name
        self.provider = provider
        self.capabilities = capabilities

    def generate_environment(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        return self._generate(prompt, output_path, seed=seed)

    def generate_character(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        return self.generate_character_reference(prompt, output_path, seed)

    def generate_character_reference(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        return self._generate(prompt, output_path, seed=seed)

    def generate_pose(
        self, prompt: str, reference: Path, output_path: Path, seed: int = 42
    ) -> Path:
        self._require_reference_support("pose")
        return self._generate(prompt, output_path, seed=seed, references=[reference])

    def generate_expression(
        self, prompt: str, reference: Path, output_path: Path, seed: int = 42
    ) -> Path:
        self._require_reference_support("expression")
        return self._generate(prompt, output_path, seed=seed, references=[reference])

    def generate_prop(self, prompt: str, output_path: Path, seed: int = 42) -> Path:
        return self._generate(prompt, output_path, seed=seed)

    def _require_reference_support(self, operation: str) -> None:
        if not self.capabilities.reference_images:
            raise NotImplementedError(
                f"{self.name} does not support reference-image {operation} generation"
            )

    def _generate(
        self, prompt: str, output_path: Path, *, seed: int,
        references: list[Path] | None = None,
    ) -> Path:
        if references:
            return self.provider.generate(
                prompt, output_path, seed=seed, reference_images=references
            )
        try:
            return self.provider.generate(prompt, output_path, seed=seed)
        except TypeError:
            return self.provider.generate(prompt, output_path)


def get_production_image_provider(override: str | None = None) -> ProductionImageProvider:
    from app.config.settings import settings

    name = str(override or settings.image_provider).lower()
    if name == "gemini":
        from app.images.gemini_provider import GeminiImagenProvider
        return ProductionImageProvider(
            "gemini", GeminiImagenProvider(),
            ProviderCapabilities(reference_images=True, image_to_image=True),
        )
    if name in {"stability", "stable_diffusion"}:
        from app.images.stability_provider import StabilityProvider
        return ProductionImageProvider("stability", StabilityProvider(), ProviderCapabilities())
    if name == "pollinations":
        from app.images.pollinations_provider import PollinationsProvider
        return ProductionImageProvider(
            "pollinations", PollinationsProvider(),
            ProviderCapabilities(deterministic_seed=True),
        )
    from app.images.placeholder_provider import PlaceholderProvider
    return ProductionImageProvider("placeholder", PlaceholderProvider(), ProviderCapabilities())

