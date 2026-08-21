"""Automated acceptance checks for cinematic shot plans and rendered assets."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

from app.cinematic.models import ShotPlan


def inspect_plan(shots: list[ShotPlan]) -> dict[str, Any]:
    checks = {
        "six_shots": len(shots) == 6,
        "thirty_seconds": round(sum(shot.duration for shot in shots), 3) == 30.0,
        "dedicated_closeup": any(shot.artwork_kind == "closeup" for shot in shots),
        "walking_action": any(shot.action == "walk" for shot in shots),
        "sitting_action": any(shot.action == "sit" for shot in shots),
        "mixed_animation_modes": {shot.animation_mode for shot in shots} == {"2d", "2.5d"},
        "varied_transitions": len({shot.transition for shot in shots}) >= 2,
        "meaningful_motion": all(
            shot.camera.movement != "static" or shot.environment_motion for shot in shots
        ),
        "period_constraints": all(bool(shot.historical_constraints) for shot in shots),
        "distinct_prompts": len({shot.image_prompt for shot in shots}) == len(shots),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "problems": [name for name, passed in checks.items() if not passed],
    }


def inspect_artwork(path: Path, expected_kind: str) -> dict[str, Any]:
    if not path.is_file():
        return {"passed": False, "problems": ["missing"], "path": str(path)}
    image = Image.open(path).convert("RGB")
    grayscale = image.convert("L")
    width, height = image.size
    metrics = {
        "width": width, "height": height,
        "entropy": round(grayscale.entropy(), 3),
        "edge_mean": round(ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES)).mean[0], 3),
    }
    checks = {
        "resolution": width >= 1024 and height >= 576,
        "aspect_ratio": abs(width / height - 16 / 9) < 0.08,
        "detail": metrics["entropy"] >= 5.0 and metrics["edge_mean"] >= 4.5,
    }
    return {
        "path": str(path.resolve()), "expected_kind": expected_kind,
        "passed": all(checks.values()), "checks": checks, "metrics": metrics,
        "problems": [name for name, passed in checks.items() if not passed],
    }
