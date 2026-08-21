"""Development provider that accepts a pre-existing real model, never primitives."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.providers.character3d.base import (
    Character3DAsset,
    Character3DProvider,
    CharacterGenerationBlocked,
    CharacterModelValidation,
)

SUPPORTED = {".glb", ".gltf", ".fbx", ".obj"}


class LocalCharacter3DProvider(Character3DProvider):
    name = "local_asset"

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = model_path

    @property
    def configured(self) -> bool:
        return bool(
            self.model_path
            and self.model_path.is_file()
            and self.model_path.suffix.lower() in SUPPORTED
        )

    def _import(self, specification: dict[str, Any], output_dir: Path) -> Character3DAsset:
        if not self.configured or self.model_path is None:
            raise CharacterGenerationBlocked(
                "LOCAL_CHARACTER_MODEL must point to an existing GLB, GLTF, FBX, or OBJ asset."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"character_model{self.model_path.suffix.lower()}"
        if self.model_path.resolve() != target.resolve():
            shutil.copy2(self.model_path, target)
        return Character3DAsset(
            character_id=str(specification.get("character_id", "character")),
            model_path=target,
            format=target.suffix.removeprefix("."),
            provider=self.name,
            metadata={"source": str(self.model_path), "requires_blender_validation": True},
        )

    def generate_from_text(self, specification, output_dir):
        return self._import(specification, output_dir)

    def generate_from_images(self, specification, references, output_dir):
        return self._import(specification, output_dir)

    def generate_variation(self, canonical, specification, output_dir):
        return self._import(specification, output_dir)

    def validate_model(self, asset):
        exists = asset.model_path.is_file() and asset.model_path.stat().st_size >= 50_000
        return CharacterModelValidation(
            passed=False,
            quality_status="requires_blender_validation" if exists else "rejected",
            model_format=asset.format,
            rejection_reasons=()
            if exists
            else ("Model is missing or too small to be a production humanoid.",),
        )
