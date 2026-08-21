"""Capability-aware contracts for the deterministic 3D pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.providers.character3d.base import Character3DProvider


@dataclass(frozen=True)
class ProviderCapabilities:
    reference_images: bool = False
    age_variations: bool = False
    facial_rig: bool = False
    humanoid_rig: bool = False
    deterministic: bool = True


class ReferenceProvider(Protocol):
    def search_person(self, name: str) -> list[dict[str, Any]]: ...
    def search_location(self, location: str, period: str) -> list[dict[str, Any]]: ...


class RigProvider(Protocol):
    capabilities: ProviderCapabilities

    def rig(self, model: Path, output_dir: Path) -> Path: ...
    def validate(self, rig: Path) -> dict[str, Any]: ...


class MotionProvider(Protocol):
    def motion(self, action: dict[str, Any], rig: Path, output_dir: Path) -> Path: ...


class RenderProvider(Protocol):
    def available(self) -> bool: ...
    def render(self, plan_path: Path, output_path: Path, quality: str = "PREVIEW") -> Path: ...


@dataclass
class ProviderRegistry:
    reference: ReferenceProvider | None = None
    character: Character3DProvider | None = None
    rig: RigProvider | None = None
    motion: MotionProvider | None = None
    render: RenderProvider | None = None
