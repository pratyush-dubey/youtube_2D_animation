"""Meaningful motion tracks for articulated characters and subtle environments."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Transform:
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0


@dataclass(frozen=True)
class PuppetFrame:
    root: Transform
    parts: dict[str, Transform]
    eye_state: str
    mouth_state: str
    contact_shadow_scale: float


class PuppetAnimator:
    def frame(self, action: str, progress: float, speed: str = "normal") -> PuppetFrame:
        progress = max(0.0, min(1.0, progress))
        if action == "walk":
            return self._walk(progress, speed)
        if action in {"look_around", "look_to_counter"}:
            turn = math.sin(progress * math.pi) * (8 if action == "look_around" else 4)
            return PuppetFrame(
                Transform(y=math.sin(progress * math.pi * 2) * 1.5),
                {"head": Transform(rotation=turn), "eyes": Transform(x=turn * 0.16)},
                "look_right" if turn > 0 else "look_left", "closed", 1.0,
            )
        if action == "sit":
            eased = progress * progress * (3 - 2 * progress)
            return PuppetFrame(
                Transform(y=92 * eased),
                {
                    "torso": Transform(rotation=8 * math.sin(eased * math.pi)),
                    "upper_leg_left": Transform(rotation=-55 * eased),
                    "upper_leg_right": Transform(rotation=-55 * eased),
                    "lower_leg_left": Transform(rotation=70 * eased),
                    "lower_leg_right": Transform(rotation=70 * eased),
                }, "focus", "closed", 1.0 - 0.12 * eased,
            )
        breath = math.sin(progress * math.pi * 2)
        return PuppetFrame(Transform(y=breath * 1.6, scale_y=1 + breath * 0.003), {}, "neutral", "closed", 1.0)

    @staticmethod
    def _walk(progress, speed):
        cycles = {"slow": 1.4, "normal": 2.0, "fast": 2.8}.get(speed, 2.0)
        phase = progress * math.tau * cycles
        swing = math.sin(phase)
        knee_left = max(0.0, -swing) * 34
        knee_right = max(0.0, swing) * 34
        # Root advances while the planted foot's backward phase cancels slide visually.
        travel = progress * 420
        bob = abs(math.sin(phase)) * -7
        parts = {
            "upper_leg_left": Transform(rotation=swing * 24),
            "lower_leg_left": Transform(rotation=knee_left),
            "foot_left": Transform(rotation=-swing * 8),
            "upper_leg_right": Transform(rotation=-swing * 24),
            "lower_leg_right": Transform(rotation=knee_right),
            "foot_right": Transform(rotation=swing * 8),
            "upper_arm_left": Transform(rotation=-swing * 18),
            "lower_arm_left": Transform(rotation=max(0, swing) * 8),
            "upper_arm_right": Transform(rotation=swing * 18),
            "lower_arm_right": Transform(rotation=max(0, -swing) * 8),
            "torso": Transform(rotation=swing * 1.5),
            "head": Transform(rotation=-swing * 0.8),
        }
        return PuppetFrame(
            Transform(x=travel, y=bob), parts, "focus", "closed",
            1.0 - abs(math.sin(phase)) * 0.08,
        )


def environment_state(motions: tuple[str, ...], progress: float) -> dict[str, float]:
    """Return restrained deterministic controls; renderers map them to real layers."""
    values: dict[str, float] = {}
    if "ceiling fan" in motions:
        values["ceiling_fan_degrees"] = progress * 720
    if "light flicker" in motions:
        values["light_intensity"] = 0.97 + math.sin(progress * 37.0) * 0.018
    if "paper movement" in motions:
        values["paper_rotation"] = math.sin(progress * math.tau * 1.7) * 1.4
    if "pedestrians" in motions or "passing pedestrian" in motions:
        values["pedestrian_offset"] = progress
    if "dust" in motions or "subtle dust" in motions:
        values["dust_phase"] = progress
    return values
