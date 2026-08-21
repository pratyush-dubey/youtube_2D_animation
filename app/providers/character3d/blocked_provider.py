"""Explicit blocked provider used when no genuine source is configured."""
from pathlib import Path

from app.providers.character3d.base import (
    BLOCKED_MESSAGE,
    Character3DProvider,
    CharacterGenerationBlocked,
    CharacterModelValidation,
)


class BlockedCharacter3DProvider(Character3DProvider):
    name = "unconfigured"

    @property
    def configured(self) -> bool:
        return False

    def _blocked(self):
        raise CharacterGenerationBlocked(BLOCKED_MESSAGE)

    def generate_from_text(self, specification, output_dir: Path):
        self._blocked()

    def generate_from_images(self, specification, references, output_dir: Path):
        self._blocked()

    def generate_variation(self, canonical, specification, output_dir: Path):
        self._blocked()

    def validate_model(self, asset):
        return CharacterModelValidation(
            passed=False,
            quality_status="blocked",
            rejection_reasons=(BLOCKED_MESSAGE,),
        )
