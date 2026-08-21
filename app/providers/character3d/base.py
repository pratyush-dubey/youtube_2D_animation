"""Contracts and records for genuine, externally produced 3D humans."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BLOCKED_MESSAGE = "Production 3D character provider is not configured."
PLACEHOLDER_REJECTION = (
    "Generated character is a procedural placeholder and cannot be used for production rendering."
)


class CharacterGenerationBlocked(RuntimeError):
    """Raised when production would otherwise substitute a fake character."""


@dataclass(frozen=True)
class Character3DAsset:
    character_id: str
    model_path: Path
    format: str
    provider: str
    textures: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    rigged: bool = False
    facial_rig: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["model_path"] = str(self.model_path)
        return value


@dataclass(frozen=True)
class CharacterModelValidation:
    passed: bool
    quality_status: str
    model_format: str = ""
    vertex_count: int = 0
    triangle_count: int = 0
    materials: tuple[str, ...] = ()
    textures: tuple[str, ...] = ()
    rig_status: str = "not_tested"
    facial_rig_status: str = "not_tested"
    animation_test_status: str = "not_tested"
    rejection_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Character3DProvider(ABC):
    """Replaceable source of actual mesh assets; Blender is only a consumer."""

    name: str

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def generate_from_text(
        self, specification: dict[str, Any], output_dir: Path
    ) -> Character3DAsset: ...

    @abstractmethod
    def generate_from_images(
        self, specification: dict[str, Any], references: list[Path], output_dir: Path
    ) -> Character3DAsset: ...

    def generate_from_reference(
        self, specification: dict[str, Any], references: list[Path], output_dir: Path
    ) -> Character3DAsset:
        return self.generate_from_images(specification, references, output_dir)

    @abstractmethod
    def generate_variation(
        self, canonical: Character3DAsset, specification: dict[str, Any], output_dir: Path
    ) -> Character3DAsset: ...

    @abstractmethod
    def validate_model(self, asset: Character3DAsset) -> CharacterModelValidation: ...
