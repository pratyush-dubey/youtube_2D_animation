"""Deterministic scene graph, shot planner, and animation quality gate.

The LLM may suggest shots, but this module always produces a complete editable
timeline.  Rendering therefore never depends on a provider returning animation
instructions in exactly the right shape.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

from app.video.blocking import character_blocking

SHOT_TYPES = {"wide", "medium", "closeup", "insert", "over_shoulder", "rear"}
CAMERA_MOVES = {
    "static", "slow_push", "dolly_in", "dolly_out", "pan_left", "pan_right",
    "pan_up", "pan_down", "track_character", "follow_character", "handheld",
    "shake", "tilt", "orbit_simulation",
}
TRANSITIONS = {
    "cut", "fade", "crossfade", "dip_to_black", "dip_to_white",
    "zoom_transition", "pan_transition", "match_cut", "whip_pan", "light_flash",
}
EXPRESSIONS = {
    "neutral", "happy", "sad", "angry", "fear", "surprised", "confused",
    "thinking", "crying", "laughing",
}


def build_production_scene(scene: dict) -> dict:
    """Return a scene with a real shot/layer/timeline production plan."""
    result = deepcopy(scene)
    duration = max(1.0, float(result.get("duration_seconds", 5.0)))
    emotion = _emotion(result)
    seed = int(result.get("seed", _seed(result)))
    shots = _normalise_shots(result.get("shots"), result, duration, emotion)
    layers = _normalise_layers(result.get("layers"), result, emotion)
    timeline = _build_timeline(result, shots, layers, duration, emotion)
    result.update({
        "production_version": 1,
        "seed": seed,
        "emotion": emotion,
        "shots": shots,
        "layers": layers,
        "timeline": timeline,
        "render_mode": "FULL_ANIMATION",
    })
    report = score_animation_plan(result)
    result["animation_quality"] = report
    if report["score"] < 70:
        result = _repair_plan(result)
        result["animation_quality"] = score_animation_plan(result)
    return result


def score_animation_plan(scene: dict) -> dict:
    """Score the plan before rendering; a plan below 70 must be repaired."""
    shots = scene.get("shots") or []
    layers = scene.get("layers") or []
    timeline = scene.get("timeline") or {}
    tracks = timeline.get("tracks") or []
    track_names = {str(t.get("name", "")) for t in tracks}
    cameras = {str(s.get("camera", {}).get("move", "static")) for s in shots}
    shot_types = {str(s.get("shot_type", "")) for s in shots}
    layer_types = {str(layer.get("type", "")) for layer in layers}
    character_actions = [
        str(shot.get("action", "idle")) for shot in shots if shot.get("characters")
    ]
    has_character_track = "character" in track_names

    scores = {
        "character_motion": (
            20 if has_character_track and any(action not in {"idle", "observe"} for action in character_actions)
            else (8 if has_character_track else 0)
        ),
        "camera_motion": 20 if any(c != "static" for c in cameras) else 0,
        "environment_motion": 20 if {"atmosphere", "environment", "lighting"} & track_names else 0,
        "visual_variation": 15 if len(shot_types) >= 3 else (10 if len(shot_types) == 2 else 3),
        "story_alignment": 15 if all(s.get("action") for s in shots) else 7,
        "audio_sync": 10 if "audio" in track_names else 0,
        "transition_quality": 5 if any(s.get("transition") in TRANSITIONS for s in shots) else 0,
    }
    score = sum(scores.values())
    return {
        "score": score,
        "threshold": 70,
        "passed": score >= 70,
        "components": scores,
        "moving_layers": sorted(layer_types & {"environment", "character", "fx", "lighting"}),
    }


def _normalise_shots(raw: Any, scene: dict, duration: float, emotion: str) -> list[dict]:
    if isinstance(raw, list) and raw:
        shots = []
        cursor = 0.0
        for index, value in enumerate(raw):
            item = value if isinstance(value, dict) else {}
            shot_duration = max(
                0.4, float(item.get("duration", item.get("duration_seconds", 1.5)) or 1.5)
            )
            shot_duration = min(shot_duration, max(duration - cursor, 0.4))
            shot_type = str(item.get("shot_type", "medium")).lower().replace("-", "_")
            if shot_type not in SHOT_TYPES:
                shot_type = "medium"
            camera = item.get("camera")
            if isinstance(camera, str):
                camera = {"move": _camera_name(camera)}
            elif not isinstance(camera, dict):
                camera = {"move": _camera_for(shot_type, emotion, index)}
            camera.setdefault("move", _camera_for(shot_type, emotion, index))
            shots.append(_shot(scene, index, cursor, shot_duration, shot_type, camera, item))
            cursor += shot_duration
            if cursor >= duration - 0.05:
                break
        if shots:
            shots[-1]["duration"] = round(shots[-1]["duration"] + max(0.0, duration - cursor), 3)
            return shots

    # Short narration beats still receive multiple visual shots. Longer scenes
    # receive four so no image is held for the full paragraph.
    if duration < 3.5:
        types = ["wide", "closeup"]
        weights = [0.55, 0.45]
    elif duration < 6.5:
        types = ["wide", "medium", "closeup"]
        weights = [0.32, 0.42, 0.26]
    else:
        types = ["wide", "medium", "closeup", "insert"]
        weights = [0.28, 0.34, 0.23, 0.15]
    cursor = 0.0
    shots = []
    for index, (shot_type, weight) in enumerate(zip(types, weights)):
        shot_duration = duration - cursor if index == len(types) - 1 else round(duration * weight, 3)
        camera = {"move": _camera_for(shot_type, emotion, index), "easing": "ease_in_out"}
        shots.append(_shot(scene, index, cursor, shot_duration, shot_type, camera, {}))
        cursor += shot_duration
    return shots


def _shot(
    scene: dict, index: int, start: float, duration: float, shot_type: str,
    camera: dict, supplied: dict,
) -> dict:
    action = str(
        supplied.get("action") or scene.get("character_action") or _extract_action(scene)
    ).lower().replace(" ", "_")
    expression = str(supplied.get("expression") or _expression_for(_emotion(scene), index))
    transition = str(supplied.get("transition") or ("cut" if index else scene.get("transition", "cut")))
    transition = transition.lower().replace("-", "_")
    if transition not in TRANSITIONS:
        transition = "crossfade" if index else "cut"
    camera["move"] = _camera_name(str(camera.get("move", "slow_push")))
    camera.setdefault("start", {"x": 0.0, "y": 0.0, "zoom": _zoom_for(shot_type)})
    end_zoom = float(camera["start"]["zoom"]) + (0.08 if camera["move"] in {"slow_push", "dolly_in"} else 0.0)
    camera.setdefault("end", {"x": 0.0, "y": 0.0, "zoom": end_zoom})
    character_position = supplied.get("character_position") or character_blocking(
        action, shot_type, _seed(scene)
    )
    return {
        "id": f"{scene.get('scene_id', 1)}{chr(65 + index)}",
        "start": round(start, 3),
        "duration": round(duration, 3),
        "shot_type": shot_type,
        "camera": camera,
        "characters": supplied.get("characters") or ([scene["character_name"]] if scene.get("character_name") else []),
        "action": action,
        "expression": expression if expression in EXPRESSIONS else "neutral",
        "subject": supplied.get("subject") or scene.get("visual_description", "story subject"),
        "transition": transition,
        "character_position": character_position,
    }


def _normalise_layers(raw: Any, scene: dict, emotion: str) -> list[dict]:
    if isinstance(raw, list) and raw:
        return raw
    layers = [
        {"id": "sky", "type": "environment", "depth": 0.0, "motion": "drift", "speed": 0.08},
        {"id": "distant", "type": "environment", "depth": 1.0, "motion": "parallax", "speed": 0.18},
        {"id": "midground", "type": "environment", "depth": 2.0, "motion": "parallax", "speed": 0.42},
        {"id": "ground", "type": "environment", "depth": 2.7, "motion": "parallax", "speed": 0.6},
    ]
    if scene.get("character_name") or scene.get("character_motion"):
        layers.append({
            "id": "character", "type": "character", "depth": 3.0,
            "asset": scene.get("character_name"), "motion": scene.get("character_motion") or "idle-breathe",
        })
    layers.extend([
        {"id": "foreground", "type": "environment", "depth": 4.0, "motion": "parallax", "speed": 0.92},
        {"id": "atmosphere", "type": "fx", "depth": 4.5, "motion": _effect_for(scene, emotion), "opacity": 0.34},
        {"id": "lighting", "type": "lighting", "depth": 5.0, "motion": "flicker", "temperature": _temperature(emotion)},
    ])
    return layers


def _build_timeline(scene: dict, shots: list[dict], layers: list[dict], duration: float, emotion: str) -> dict:
    tracks = [
        {"name": "camera", "clips": [
            {"start": s["start"], "duration": s["duration"], "shot_id": s["id"], "keyframes": s["camera"]}
            for s in shots
        ]},
        {"name": "environment", "clips": [
            {"start": 0.0, "duration": duration, "layer": layer["id"], "motion": layer.get("motion", "parallax")}
            for layer in layers if layer.get("type") == "environment"
        ]},
        {"name": "atmosphere", "clips": [
            {"start": 0.0, "duration": duration, "effect": layer.get("motion", "fog")}
            for layer in layers if layer.get("type") == "fx"
        ]},
        {"name": "lighting", "clips": [
            {"start": 0.0, "duration": duration, "effect": layer.get("motion", "flicker")}
            for layer in layers if layer.get("type") == "lighting"
        ]},
        {"name": "audio", "clips": [
            {"start": 0.0, "duration": duration, "type": "voice"},
            *[{"start": round(s["start"] + min(0.25, s["duration"] / 3), 3), "duration": 0.7, "type": "sfx", "cue": cue}
              for s, cue in zip(shots, scene.get("sfx") or [])],
        ]},
    ]
    if any(layer.get("type") == "character" for layer in layers):
        tracks.append({"name": "character", "clips": [
            {
                "start": s["start"], "duration": s["duration"], "shot_id": s["id"],
                "action": s["action"], "expression": s["expression"],
                "keyframes": {
                    "position": [{"time": 0.0, "value": [0.12, 0.94]}, {"time": 1.0, "value": [0.62, 0.94]}],
                    "breathing": [{"time": 0.0, "value": 0.0}, {"time": 1.0, "value": 1.0}],
                    "blink": [{"time": 0.0, "value": 0.0}, {"time": 0.55, "value": 1.0}, {"time": 0.62, "value": 0.0}],
                },
            }
            for s in shots
        ]})
    return {"duration": round(duration, 3), "fps": 30, "tracks": tracks, "emotion": emotion}


def _repair_plan(scene: dict) -> dict:
    repaired = deepcopy(scene)
    tracks = repaired["timeline"]["tracks"]
    names = {t["name"] for t in tracks}
    duration = float(repaired["duration_seconds"])
    for name, effect in (("environment", "parallax"), ("atmosphere", "fog"), ("lighting", "flicker"), ("audio", "voice")):
        if name not in names:
            tracks.append({"name": name, "clips": [{"start": 0.0, "duration": duration, "effect": effect}]})
    for index, shot in enumerate(repaired["shots"]):
        if shot["camera"]["move"] == "static":
            shot["camera"]["move"] = "slow_push" if index % 2 == 0 else "pan_right"
    repaired["render_mode"] = "PROCEDURAL_ANIMATION"
    return repaired


def _extract_action(scene: dict) -> str:
    text = f"{scene.get('narration', '')} {scene.get('visual_description', '')}".lower()
    patterns = [
        (r"\bwalk(?:s|ed|ing)?\b", "walk"), (r"\brun(?:s|ning)?\b", "run"),
        (r"\bopen(?:s|ed|ing)?\b", "open_object"), (r"\bturn(?:s|ed|ing)?\b", "turn_head"),
        (r"\bstop(?:s|ped|ping)?\b", "stop"), (r"\blook(?:s|ed|ing)?\b", "look_around"),
        (r"\braise(?:s|d|ing)?\b", "raise_hand"), (r"\bspeak(?:s|ing)?\b|\bsaid\b", "talk"),
    ]
    return next((action for pattern, action in patterns if re.search(pattern, text)), "react")


def _emotion(scene: dict) -> str:
    raw = str(scene.get("emotion") or scene.get("voice_emotion") or scene.get("music_mood") or "serious").lower()
    aliases = {"tense": "fear", "eerie": "fear", "mysterious": "fear", "uplifting": "happy", "hopeful": "happy", "dramatic": "surprised"}
    return aliases.get(raw, raw if raw in EXPRESSIONS else "neutral")


def _expression_for(emotion: str, index: int) -> str:
    if emotion == "fear":
        return ("neutral", "confused", "fear", "surprised")[min(index, 3)]
    return emotion if emotion in EXPRESSIONS else "neutral"


def _camera_for(shot_type: str, emotion: str, index: int) -> str:
    if shot_type == "wide":
        return "slow_push"
    if shot_type == "medium":
        return "track_character" if index % 2 else "pan_right"
    if shot_type == "closeup":
        return "handheld" if emotion in {"fear", "angry"} else "dolly_in"
    if shot_type in {"rear", "over_shoulder"}:
        return "orbit_simulation"
    return "slow_push"


def _camera_name(value: str) -> str:
    key = value.lower().strip().replace("-", "_").replace(" ", "_")
    aliases = {"zoom_in": "dolly_in", "zoom_out": "dolly_out", "tracking": "track_character", "push_in": "slow_push"}
    key = aliases.get(key, key)
    return key if key in CAMERA_MOVES else "slow_push"


def _zoom_for(shot_type: str) -> float:
    return {"wide": 1.0, "medium": 1.18, "closeup": 1.62, "insert": 1.8, "over_shoulder": 1.3, "rear": 1.2}.get(shot_type, 1.1)


def _effect_for(scene: dict, emotion: str) -> str:
    text = f"{scene.get('visual_description', '')} {scene.get('image_prompt', '')}".lower()
    for effect in ("rain", "snow", "fog", "smoke", "dust", "fire", "water", "leaves"):
        if effect in text:
            return effect
    return "fog" if emotion == "fear" else "dust"


def _temperature(emotion: str) -> int:
    return {"fear": 3800, "sad": 4300, "angry": 3200, "happy": 6200}.get(emotion, 5000)


def _seed(scene: dict) -> int:
    raw = f"{scene.get('scene_id')}|{scene.get('narration')}|{scene.get('visual_description')}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)
