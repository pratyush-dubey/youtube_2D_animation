"""Animate segmented illustrated character artwork without drawing visible geometry."""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageEnhance


class IllustratedCharacterRig:
    def __init__(self, manifest_path: Path, expressions: dict[str, str] | None = None) -> None:
        self.manifest_path = manifest_path
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.canvas_size = tuple(self.manifest["canvas_size"])
        self.parts = {
            name: (Image.open(data["path"]).convert("RGBA"), data)
            for name, data in self.manifest["parts"].items()
        }
        self.expressions = {
            name: Image.open(path).convert("RGBA")
            for name, path in (expressions or {}).items() if Path(path).exists()
        }
        self._scaled_cache: dict[int, dict] = {}

    def render(
        self,
        height: int,
        *,
        phase: float,
        action: str,
        expression: str,
        head_turn: float,
        breathing: float,
        closeup: bool = False,
    ) -> Image.Image:
        if closeup and expression in {"fear", "surprised"} and "fear" in self.expressions:
            return self._expression_frame(height, phase, head_turn)
        scaled = self._scaled(max(80, height))
        canvas = Image.new("RGBA", scaled["canvas_size"], (0, 0, 0, 0))
        walking = action in {"walk", "walking", "run", "walk_across"}
        gait = math.sin(phase) if walking else 0.0
        anticipation = _anticipation(action, phase)
        angles = {
            "left_leg": gait * 3.2,
            "right_leg": -gait * 3.2,
            "left_arm": -gait * 4.2 - anticipation * 1.0,
            "right_arm": gait * 4.2 + anticipation * 1.5,
            "torso": -gait * 0.45 + anticipation * 0.35,
            "head": math.sin(phase * 0.24) * 0.4 + head_turn * 1.4,
        }
        offsets = {
            "left_leg": (gait * 2.2, abs(gait) * 1.4),
            "right_leg": (-gait * 2.2, abs(gait) * 1.4),
            "left_arm": (0.0, 0.0), "right_arm": (0.0, 0.0),
            "torso": (0.0, -abs(gait) * 1.7),
            "head": (head_turn * 2.0, -abs(gait) * 1.0),
        }
        for name in ("left_leg", "right_leg", "left_arm", "right_arm", "torso", "head"):
            if name not in scaled["parts"]:
                continue
            image, data = scaled["parts"][name]
            if name == "torso" and abs(breathing - 1.0) > 0.001:
                image = _scale_about_center(image, breathing, 1.0)
            if name == "head" and head_turn:
                image = _scale_about_center(image, 1.0 - min(abs(head_turn), 1.0) * 0.035, 1.0)
            transformed, position = _rotate_about_pivot(
                image, angles[name], tuple(data["pivot_pixels"]), tuple(data["position"])
            )
            dx, dy = offsets[name]
            canvas.alpha_composite(transformed, (round(position[0] + dx), round(position[1] + dy)))
        return _environment_integrate(canvas)

    def _scaled(self, target_height: int) -> dict:
        key = int(round(target_height / 8) * 8)
        if key in self._scaled_cache:
            return self._scaled_cache[key]
        scale = key / self.canvas_size[1]
        canvas_size = (max(2, round(self.canvas_size[0] * scale)), key)
        parts = {}
        for name, (image, data) in self.parts.items():
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            resized = image.resize(size, Image.Resampling.LANCZOS)
            pivot = data["pivot"]
            parts[name] = (
                resized,
                {
                    "position": [round(data["position"][0] * scale), round(data["position"][1] * scale)],
                    "pivot_pixels": [pivot[0] * resized.width, pivot[1] * resized.height],
                },
            )
        result = {"canvas_size": canvas_size, "parts": parts}
        self._scaled_cache[key] = result
        return result

    def _expression_frame(self, target_height: int, phase: float, head_turn: float) -> Image.Image:
        source = self.expressions["fear"]
        bbox = source.getchannel("A").getbbox() or (0, 0, source.width, source.height)
        source = source.crop(bbox)
        scale = target_height / source.height
        size = (max(2, round(source.width * scale)), max(2, target_height))
        image = source.resize(size, Image.Resampling.LANCZOS)
        sway = math.sin(phase * 0.22) * 0.7 + head_turn * 1.1
        image = image.rotate(sway, Image.Resampling.BICUBIC, expand=True)
        return _environment_integrate(image)


def _rotate_about_pivot(
    image: Image.Image,
    angle: float,
    pivot: tuple[float, float],
    base_position: tuple[int, int],
) -> tuple[Image.Image, tuple[float, float]]:
    padding = max(image.width, image.height) // 2 + 12
    size = (image.width + padding * 2, image.height + padding * 2)
    center = (size[0] / 2, size[1] / 2)
    paste_at = (round(center[0] - pivot[0]), round(center[1] - pivot[1]))
    stage = Image.new("RGBA", size, (0, 0, 0, 0))
    stage.alpha_composite(image, paste_at)
    rotated = stage.rotate(angle, Image.Resampling.BICUBIC, center=center, expand=False)
    position = (
        base_position[0] + pivot[0] - center[0],
        base_position[1] + pivot[1] - center[1],
    )
    return rotated, position


def _scale_about_center(image: Image.Image, sx: float, sy: float) -> Image.Image:
    resized = image.resize(
        (max(1, round(image.width * sx)), max(1, round(image.height * sy))),
        Image.Resampling.BICUBIC,
    )
    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((image.width - resized.width) // 2, (image.height - resized.height) // 2))
    return canvas


def _environment_integrate(image: Image.Image) -> Image.Image:
    colored = ImageEnhance.Color(image).enhance(0.88)
    overlay = Image.new("RGBA", colored.size, (40, 78, 92, 0))
    overlay.putalpha(colored.getchannel("A").point(lambda value: round(value * 0.07)))
    return Image.alpha_composite(colored, overlay)


def _anticipation(action: str, phase: float) -> float:
    if action in {"turn_head", "react", "stop", "look_around"}:
        return math.sin(min(math.pi, max(0.0, phase * 0.18)))
    return 0.0
