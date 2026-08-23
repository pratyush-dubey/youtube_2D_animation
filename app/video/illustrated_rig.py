"""Hierarchical 2D skeletal animation for approved raster character artwork."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import cv2
from PIL import Image, ImageEnhance


@dataclass(frozen=True)
class RigTelemetry:
    action: str
    root: tuple[float, float]
    joints: dict[str, tuple[float, float]]
    part_angles: dict[str, float]
    planted_foot: str | None
    foot_targets: dict[str, tuple[float, float]]


class IllustratedCharacterRig:
    """Render source-derived layers through a parent-child skeleton.

    Root travel is deliberately excluded. Scene locomotion is supplied by the
    compositor only after this rig has produced articulation, preventing a
    translated monolithic PNG from masquerading as a walk.
    """

    WALK_CYCLE_FRAMES = 16

    def __init__(self, manifest_path: Path, expressions: dict[str, str] | None = None) -> None:
        self.manifest_path = manifest_path
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(self.manifest.get("rig_version", 0)) < 3:
            raise ValueError("Legacy stripe rig rejected: rebuild a rig_version 3 articulated skeleton")
        if self.manifest.get("representation") != "segmented_artwork_skeleton":
            raise ValueError("Character representation must be segmented_artwork_skeleton")
        self.canvas_size = tuple(self.manifest["canvas_size"])
        self.parts = {
            name: (Image.open(data["path"]).convert("RGBA"), data)
            for name, data in self.manifest["parts"].items()
        }
        source_path = Path(self.manifest["source_path"])
        self.source = Image.open(source_path).convert("RGBA")
        self.joints = {name: tuple(map(float, point)) for name, point in self.manifest["joints"].items()}
        self.expressions = {
            name: Image.open(path).convert("RGBA")
            for name, path in (expressions or {}).items() if Path(path).exists()
        }
        self.last_telemetry: RigTelemetry | None = None

    def render(
        self, height: int, *, phase: float, action: str, expression: str,
        head_turn: float, breathing: float, closeup: bool = False,
        progress: float = 0.0, mouth_open: float = 0.0,
    ) -> Image.Image:
        del expression, breathing
        scale = max(80, int(height)) / self.canvas_size[1]
        size = (max(2, round(self.canvas_size[0] * scale)), max(80, int(height)))
        pose = self._pose(action, phase, progress, head_turn, scale, mouth_open)
        canvas = self._deform_source(size, pose, scale)
        if closeup:
            bbox = canvas.getchannel("A").getbbox()
            if bbox:
                bottom = min(canvas.height, bbox[1] + round((bbox[3] - bbox[1]) * .48))
                canvas = canvas.crop((bbox[0], bbox[1], bbox[2], bottom))
                target_h = max(80, int(height))
                canvas.thumbnail((round(target_h * .9), target_h), Image.Resampling.LANCZOS)
        self.last_telemetry = pose
        return _environment_integrate(canvas)

    def _deform_source(self, size: tuple[int, int], pose: RigTelemetry, scale: float) -> Image.Image:
        """Continuously skin approved artwork to the skeleton without cut seams."""
        source = np.asarray(self.source.resize(size, Image.Resampling.LANCZOS), dtype=np.uint8)
        height, width = source.shape[:2]
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        # Major controls carry the mesh; facial feature controls inherit the
        # head and are intentionally excluded to protect identity detail.
        control_names = ["hips", "spine", "chest", "neck", "head",
                         "shoulder_l", "elbow_l", "wrist_l", "shoulder_r", "elbow_r", "wrist_r",
                         "hip_l", "knee_l", "ankle_l", "toe_l", "hip_r", "knee_r", "ankle_r", "toe_r"]
        if "mouth" in self.joints:
            control_names.append("mouth")
        weight_sum = np.full((height, width), 1e-5, np.float32)
        dx_sum = np.zeros((height, width), np.float32)
        dy_sum = np.zeros((height, width), np.float32)
        radius = max(18.0, width * .14)
        for name in control_names:
            sx, sy = self.joints[name][0] * scale, self.joints[name][1] * scale
            dx, dy = pose.joints[name][0] - sx, pose.joints[name][1] - sy
            distance2 = (xx - sx) ** 2 + (yy - sy) ** 2
            weight = np.exp(-distance2 / (2.0 * radius * radius)).astype(np.float32)
            # Distal controls need tighter influence so a swinging wrist does
            # not bend the torso or alter the face; the mouth needs an even
            # tighter kernel so a viseme does not drag the nose or chin.
            if name.startswith(("wrist", "ankle", "toe")):
                weight *= np.exp(-distance2 / (2.0 * (radius*.62) ** 2)).astype(np.float32)
            elif name == "mouth":
                weight *= np.exp(-distance2 / (2.0 * (radius*.22) ** 2)).astype(np.float32)
            weight_sum += weight
            dx_sum += weight * dx
            dy_sum += weight * dy
        map_x = (xx - dx_sum / weight_sum).astype(np.float32)
        map_y = (yy - dy_sum / weight_sum).astype(np.float32)
        warped = cv2.remap(source, map_x, map_y, cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        return Image.fromarray(warped, "RGBA")

    def _pose(
        self, action: str, phase: float, progress: float, head_turn: float, scale: float,
        mouth_open: float = 0.0,
    ) -> RigTelemetry:
        action = str(action).lower()
        walking = action in {"walk", "walking", "run", "walk_across", "enter", "enter_room", "exit_room"}
        angles = {name: 0.0 for name in self.parts}
        root_x = root_y = 0.0
        planted = None
        foot_targets: dict[str, tuple[float, float]] = {}
        if walking:
            cycle = (phase / math.tau) % 1.0
            s, c = math.sin(cycle * math.tau), math.cos(cycle * math.tau)
            root_y = (-4.5 * abs(s) + 1.5 * math.cos(cycle * math.tau * 2)) * scale
            root_x = 3.0 * math.sin(cycle * math.tau * 2) * scale
            planted = "left" if c >= 0 else "right"
            angles.update({
                "left_upper_leg": 24*s, "left_lower_leg": 7 + 34*max(0.0, -s), "left_foot": -11*s - 8*max(0.0, s),
                "right_upper_leg": -24*s, "right_lower_leg": 7 + 34*max(0.0, s), "right_foot": 11*s - 8*max(0.0, -s),
                "left_upper_arm": -18*s, "left_lower_arm": 8 + 10*max(0.0, s),
                "right_upper_arm": 18*s, "right_lower_arm": 8 + 10*max(0.0, -s),
                "torso": -2.0*s, "neck": 1.2*s, "head": 0.6*s,
            })
            for side, sign in (("left", 1.0), ("right", -1.0)):
                local = math.sin(cycle * math.tau + (0 if side == "left" else math.pi))
                base = self.joints[f"ankle_{side[0]}"]
                lift = max(0.0, local) * 22.0
                foot_targets[side] = ((base[0] + sign*local*32.0)*scale + root_x, base[1]*scale - lift*scale + root_y)
        elif action in {"look_around", "look_left", "look_right", "turn_head", "scan"}:
            wave = math.sin(_smooth(progress) * math.tau - math.pi/2)
            angles["head"] = 10.0 * wave + head_turn * 3.0
            angles["neck"] = 2.5 * wave
            root_y = math.sin(progress * math.pi) * -1.5 * scale
        elif action in {"open_door", "close_door", "interact", "pick_up_object", "reach"}:
            reach = _smooth(min(1.0, progress * 1.35))
            angles.update({"torso": -3.5*reach, "right_upper_arm": -48*reach,
                           "right_lower_arm": -36*reach, "right_hand": 12*reach,
                           "head": -4*reach, "left_upper_arm": 5*reach})
        elif action == "stop":
            settle = math.sin(min(1.0, progress) * math.pi)
            root_y = -3.0 * settle * scale
            angles.update({"torso": 2.4*settle, "left_upper_leg": -4*settle,
                           "right_upper_leg": 4*settle, "head": -1.8*settle})
        else:
            breath = math.sin(phase * .35)
            root_y = -1.4 * breath * scale
            angles.update({"torso": .5*breath, "head": -.35*breath})
        matrices = self._part_matrices(angles, (root_x, root_y), scale)
        joints = {}
        for name, point in self.joints.items():
            local = (point[0] * scale, point[1] * scale)
            if name == "mouth":
                # Amplitude-driven jaw drop; the tight mesh-warp kernel above
                # keeps this from disturbing the rest of the face.
                local = (local[0], local[1] + 7.0 * scale * max(0.0, min(1.0, mouth_open)))
            joints[name] = _transform_point(matrices[_owner_for_joint(name)], local)
        return RigTelemetry(action, (root_x, root_y), joints, angles, planted, foot_targets)

    def _part_matrices(self, angles: dict[str, float], root: tuple[float, float], scale: float) -> dict[str, np.ndarray]:
        root_matrix = _translation(*root)
        result: dict[str, np.ndarray] = {}
        parents = self.manifest["parents"]

        def build(name: str) -> np.ndarray:
            if name in result:
                return result[name]
            parent = parents.get(name)
            parent_matrix = build(parent) if parent else root_matrix
            point = self.joints[self.parts[name][1]["joint"]]
            pivot = (point[0] * scale, point[1] * scale)
            result[name] = parent_matrix @ _rotation_about(float(angles.get(name, 0.0)), pivot)
            return result[name]

        for name in self.parts:
            build(name)
        return result


def _owner_for_joint(name: str) -> str:
    if name in {"hips", "spine", "chest"}: return "torso"
    if name == "neck": return "neck"
    if name in {"head", "mouth"}: return "head"
    prefixes = (("shoulder_l", "left_upper_arm"), ("elbow_l", "left_lower_arm"),
                ("wrist_l", "left_hand"), ("shoulder_r", "right_upper_arm"),
                ("elbow_r", "right_lower_arm"), ("wrist_r", "right_hand"),
                ("hip_l", "left_upper_leg"), ("knee_l", "left_lower_leg"),
                ("ankle_l", "left_foot"), ("toe_l", "left_foot"),
                ("hip_r", "right_upper_leg"), ("knee_r", "right_lower_leg"),
                ("ankle_r", "right_foot"), ("toe_r", "right_foot"))
    return next((owner for prefix, owner in prefixes if name.startswith(prefix)), "torso")


def _translation(x: float, y: float) -> np.ndarray:
    return np.array(((1.0, 0.0, x), (0.0, 1.0, y), (0.0, 0.0, 1.0)), dtype=float)


def _rotation_about(degrees: float, pivot: tuple[float, float]) -> np.ndarray:
    angle = math.radians(degrees); c, s = math.cos(angle), math.sin(angle)
    rotation = np.array(((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0)), dtype=float)
    return _translation(*pivot) @ rotation @ _translation(-pivot[0], -pivot[1])


def _rotate_crop(image: Image.Image, angle: float, pivot: tuple[float, float],
                 target: tuple[float, float]) -> tuple[Image.Image, tuple[int, int]]:
    # Facial layers and shoulder crops may have their controlling joint outside
    # their own bbox. Size the rotation stage from the pivot, not the crop size,
    # otherwise those source-derived layers are clipped into rectangular holes.
    radius = math.ceil(max(pivot[0], image.width-pivot[0], pivot[1], image.height-pivot[1], 1)) + 8
    size = (radius * 2, radius * 2)
    center = (size[0] / 2, size[1] / 2)
    stage = Image.new("RGBA", size, (0, 0, 0, 0))
    stage.alpha_composite(image, (round(center[0] - pivot[0]), round(center[1] - pivot[1])))
    rotated = stage.rotate(angle, Image.Resampling.BICUBIC, center=center, expand=False)
    return rotated, (round(target[0] - center[0]), round(target[1] - center[1]))


def _transform_point(matrix: np.ndarray, point: tuple[float, float]) -> tuple[float, float]:
    result = matrix @ np.array((point[0], point[1], 1.0))
    return float(result[0]), float(result[1])


def _smooth(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _environment_integrate(image: Image.Image) -> Image.Image:
    colored = ImageEnhance.Color(image).enhance(0.90)
    overlay = Image.new("RGBA", colored.size, (35, 70, 82, 0))
    overlay.putalpha(colored.getchannel("A").point(lambda value: round(value * 0.055)))
    return Image.alpha_composite(colored, overlay)
