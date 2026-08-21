"""Render profiles and strict preflight for the layered acceptance proof."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.cinematic.layers import LayerAsset
from app.cinematic.models import ShotPlan
from app.cinematic.puppet import PuppetRig


@dataclass(frozen=True)
class RenderProfile:
    name: str
    width: int
    height: int
    internal_fps: int
    output_fps: int = 30
    full_effects: bool = True


DRAFT = RenderProfile("DRAFT", 960, 540, 12, 30, False)
FINAL = RenderProfile("FINAL", 1920, 1080, 24, 30, True)


class RenderPreflightFailed(RuntimeError):
    pass


def preflight_shot(shot: ShotPlan, layers: list[LayerAsset], puppet: PuppetRig | None) -> dict:
    problems = []
    categories = {layer.category for layer in layers}
    if not {"background", "foreground"}.issubset(categories):
        problems.append("missing foreground/background separation")
    if shot.character_id and "character" not in categories:
        problems.append("character layer missing")
    if shot.action in {"walk", "sit", "look_around", "look_to_counter"} and puppet is None:
        problems.append("articulated puppet required for character action")
    if shot.animation_mode == "2.5d" and len({layer.parallax_speed for layer in layers}) < 2:
        problems.append("2.5D layers do not have distinct parallax speeds")
    if shot.artwork_kind == "closeup":
        closeup_paths = [Path(layer.path).name.lower() for layer in layers]
        if not any("close" in name or "face" in name for name in closeup_paths):
            problems.append("dedicated close-up artwork is missing")
    if problems:
        raise RenderPreflightFailed(f"{shot.shot_id}: " + "; ".join(problems))
    return {"passed": True, "shot_id": shot.shot_id, "layer_count": len(layers)}
