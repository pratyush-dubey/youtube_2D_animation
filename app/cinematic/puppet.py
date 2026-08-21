"""Articulated cutout rig records; production requires real painted part layers."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_PARTS = (
    "torso", "neck", "head", "eyes", "eyebrows", "mouth",
    "upper_arm_left", "lower_arm_left", "hand_left",
    "upper_arm_right", "lower_arm_right", "hand_right",
    "upper_leg_left", "lower_leg_left", "foot_left",
    "upper_leg_right", "lower_leg_right", "foot_right",
)

PARENTS = {
    "neck": "torso", "head": "neck", "eyes": "head", "eyebrows": "head", "mouth": "head",
    "upper_arm_left": "torso", "lower_arm_left": "upper_arm_left", "hand_left": "lower_arm_left",
    "upper_arm_right": "torso", "lower_arm_right": "upper_arm_right", "hand_right": "lower_arm_right",
    "upper_leg_left": "torso", "lower_leg_left": "upper_leg_left", "foot_left": "lower_leg_left",
    "upper_leg_right": "torso", "lower_leg_right": "upper_leg_right", "foot_right": "lower_leg_right",
}


@dataclass(frozen=True)
class PuppetPart:
    name: str
    path: str
    anchor: tuple[float, float]
    position: tuple[float, float]
    parent: str | None
    z_depth: float
    rotation: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)


@dataclass(frozen=True)
class PuppetPose:
    name: str
    transforms: dict[str, dict[str, Any]]


class PuppetRig:
    def __init__(self, character_id: str, parts: dict[str, PuppetPart], canvas_size: tuple[int, int]) -> None:
        self.character_id = character_id
        self.parts = parts
        self.canvas_size = canvas_size
        missing = sorted(set(REQUIRED_PARTS) - set(parts))
        if missing:
            raise ValueError("Production puppet is missing articulated parts: " + ", ".join(missing))
        for name, part in parts.items():
            if not Path(part.path).is_file():
                raise FileNotFoundError(part.path)
            expected = PARENTS.get(name)
            if expected != part.parent:
                raise ValueError(f"Invalid parent for {name}: expected {expected!r}")

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "rig_version": 1, "character_id": self.character_id,
            "canvas_size": list(self.canvas_size),
            "parts": {name: asdict(part) for name, part in self.parts.items()},
        }, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        parts = {name: PuppetPart(**value) for name, value in raw["parts"].items()}
        return cls(raw["character_id"], parts, tuple(raw["canvas_size"]))


MOUTH_STATES = ("closed", "open_small", "open_medium", "open_large", "O", "E", "A", "M", "F_V")
EYE_STATES = ("neutral", "blink", "look_left", "look_right", "look_up", "look_down", "focus", "wide", "narrow")
HEAD_STATES = ("neutral", "small_nod", "turn_left", "turn_right", "look_up", "look_down", "reaction")


def validate_pose_library(poses: dict[str, PuppetPose]) -> None:
    required = {"walking", "sitting", "looking_left", "looking_right", "surprised"}
    missing = sorted(required - set(poses))
    if missing:
        raise ValueError("Pose library is incomplete: " + ", ".join(missing))
    for pose in poses.values():
        unknown = set(pose.transforms) - set(REQUIRED_PARTS)
        if unknown:
            raise ValueError(f"Pose {pose.name} references unknown parts: {sorted(unknown)}")
