"""Validated records shared by the cinematic 2D/2.5D pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ArtDirection:
    style: str = "cinematic_illustrated_documentary"
    medium: str = "2d_digital_painting"
    detail: str = "high"
    lighting: str = "cinematic"
    texture: str = "subtle_painterly"
    color_grading: str = "cinematic"
    depth: str = "strong"
    linework: str = "subtle"
    realism: str = "stylized_natural_anatomy"
    palette: tuple[str, ...] = ("warm umber", "muted teal", "aged cream", "deep charcoal")
    negative_constraints: tuple[str, ...] = (
        "slideshow", "Ken Burns zoom", "flat vector art", "primitive 3D",
        "extra limbs", "distorted hands", "duplicate people", "text artifacts",
        "modern objects", "watermark",
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def prompt_block(self) -> str:
        return (
            f"STYLE: {self.style}; MEDIUM: {self.medium}; DETAIL: {self.detail}; "
            f"LIGHTING: {self.lighting}; TEXTURE: {self.texture}; COLOR: {self.color_grading}, "
            f"controlled palette ({', '.join(self.palette)}); DEPTH: {self.depth}; "
            f"LINEWORK: {self.linework}; REALISM: {self.realism}. "
            f"NEGATIVE CONSTRAINTS: {', '.join(self.negative_constraints)}."
        )


@dataclass(frozen=True)
class CharacterBible:
    character_id: str
    name: str
    fictional: bool
    age_stage: Literal["young", "adult", "middle-aged", "older", "final-years"]
    heritage: str
    face: str
    hair: str
    skin: str
    body: str
    clothing: str
    colors: tuple[str, ...]
    proportions: str = "natural adult anatomy"
    disclosure: str = "Dramatic reconstruction"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CameraPlan:
    framing: str
    lens_mm: int
    angle: str
    movement: str
    strength: float
    focus: str


@dataclass(frozen=True)
class LayerPlan:
    layer_id: str
    category: str
    depth: float
    parallax_speed: float
    required: bool = True


@dataclass(frozen=True)
class ShotPlan:
    shot_id: str
    start: float
    duration: float
    shot_type: str
    animation_mode: Literal["2d", "2.5d"]
    action: str
    emotion: str
    character_pose: str
    artwork_kind: Literal["environment", "full_body", "medium", "closeup", "sitting"]
    camera: CameraPlan
    layers: tuple[LayerPlan, ...]
    lighting: str
    atmosphere: tuple[str, ...]
    environment_motion: tuple[str, ...]
    transition: str
    image_prompt: str
    historical_constraints: tuple[str, ...]
    character_id: str | None = None
    audio: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.duration <= 0:
            raise ValueError("Shot duration must be positive")
        if not self.layers:
            raise ValueError("A cinematic shot must declare depth layers")
        speeds = {round(layer.parallax_speed, 3) for layer in self.layers}
        if self.animation_mode == "2.5d" and len(speeds) < 2:
            raise ValueError("A 2.5D shot needs different parallax speeds")
        if self.artwork_kind == "closeup" and "close" not in self.camera.framing.lower():
            raise ValueError("Dedicated close-up artwork requires close-up framing")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
