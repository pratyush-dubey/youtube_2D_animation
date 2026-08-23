"""Build the production clock from measured narration, never text estimates."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from app.config.settings import settings
from app.video.blocking import character_blocking


ACTION_PATTERNS = (
    (r"\bwalk(?:s|ed|ing)?\b|\bapproach(?:es|ed|ing)?\b", "walk"),
    (r"\bstop(?:s|ped|ping)?\b|\bhalt(?:s|ed|ing)?\b", "stop"),
    (r"\blook(?:s|ed|ing)?\s+(?:to\s+the\s+)?left\b", "look_left"),
    (r"\blook(?:s|ed|ing)?\s+(?:to\s+the\s+)?right\b", "look_right"),
    (r"\blook(?:s|ed|ing)?\s+around\b|\bscan(?:s|ned|ning)?\b", "look_around"),
    (r"\benter(?:s|ed|ing)?\b", "enter_room"),
    (r"\bexit(?:s|ed|ing)?\b|\bleav(?:e|es|ing|ed)\b", "exit_room"),
    (r"\bopen(?:s|ed|ing)?\b.*\bdoor\b", "open_door"),
    (r"\bclose(?:s|d|ing)?\b.*\bdoor\b", "close_door"),
    (r"\bpick(?:s|ed|ing)?\s+up\b", "pick_up_object"),
    (r"\bput(?:s|ting)?\s+down\b", "put_down_object"),
    (r"\bsit(?:s|ting)?\b", "sit"),
    (r"\bstand(?:s|ing)?\s+up\b", "stand_up"),
    (r"\bturn(?:s|ed|ing)?\b.*\bhead\b", "turn_head"),
    (r"\bpoint(?:s|ed|ing)?\b", "point"),
    (r"\bnod(?:s|ded|ding)?\b", "nod"),
    (r"\breact(?:s|ed|ing)?\b", "react"),
)

MOTION_ACTIONS = {
    "walk", "run", "stop", "look_left", "look_right", "look_around",
    "enter_room", "exit_room", "open_door", "close_door", "pick_up_object",
    "put_down_object", "sit", "stand_up", "turn_head", "point", "nod", "react",
}


def measure_audio_duration(path: Path) -> float:
    result = subprocess.run(
        [
            settings.ffprobe_path, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError(f"Narration has no measurable duration: {path}")
    return round(duration, 3)


def build_master_timeline(
    narration_segments: Iterable[dict[str, Any]],
    *,
    character_id: str | None = None,
    environment: str = "documentary reconstruction",
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Map sentence-sized TTS assets onto one monotonic master clock."""
    cursor = 0.0
    shots: list[dict[str, Any]] = []
    narration_track: list[dict[str, Any]] = []
    subtitle_track: list[dict[str, Any]] = []
    previous_framing = "closeup"

    for index, source in enumerate(narration_segments, 1):
        audio_path = Path(str(source["audio_path"]))
        duration = measure_audio_duration(audio_path)
        text = _clean_text(str(source.get("text", "")))
        actions = extract_actions(text)
        start, end = round(cursor, 3), round(cursor + duration, 3)
        shot_id = str(source.get("shot_id") or f"S{index:03d}")
        framing = _framing_for(index, previous_framing)
        previous_framing = framing
        actor = source.get("character_id", character_id)
        if not actor and any(action in MOTION_ACTIONS for action in actions):
            actions = ["environment_activity"]
        action = _primary_action(actions)
        camera = _camera_for(action, framing, shot_id)
        seed = int(hashlib.sha256(f"{shot_id}|{text}".encode("utf-8")).hexdigest()[:8], 16)
        character_position = character_blocking(action, framing, seed)
        sfx = _sfx_for(actions, environment)
        visual_type = str(source.get("visual_type") or "ai_reconstruction")
        shot = {
            "shot_id": shot_id,
            "start": start,
            "end": end,
            "duration": duration,
            "narration_segment": {
                "start": start, "end": end, "text": text,
                "audio_path": str(audio_path.resolve()),
            },
            "dialogue_segment": None,
            "characters": [actor] if actor else [],
            "environment": str(source.get("environment") or environment),
            "actions": actions,
            "action": action,
            "emotion": str(source.get("emotion") or _emotion(text)),
            "camera": camera,
            "framing": framing,
            "character_position": character_position,
            "sound_effects": sfx,
            "music": str(source.get("music") or "restrained_tension"),
            "transition": "cut" if index == 1 else "dissolve",
            "visual_type": visual_type,
            "still_image_shot": visual_type in {"historical_photo", "document"},
            "animation_plan": _animation_plan(actions, actor, environment),
        }
        shots.append(shot)
        narration_track.append({
            "event_id": f"N{index:03d}", "start": start, "end": end,
            "duration": duration, "text": text, "audio_path": str(audio_path.resolve()),
        })
        subtitle_track.append({
            "cue_id": index, "start": start, "end": end, "text": text,
            "source_event_id": f"N{index:03d}",
        })
        cursor = end

    timeline = {
        "schema_version": "2.0",
        "clock": "measured_narration_seconds",
        "duration": round(cursor, 3),
        "tracks": {
            "narration": narration_track,
            "dialogue": [],
            "sfx": [event for shot in shots for event in _timed_sfx(shot)],
            "ambience": _ambience_track(shots),
            "music": _music_track(shots),
            "subtitles": subtitle_track,
        },
        "shots": shots,
    }
    validate_master_timeline(timeline)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    return timeline


def validate_master_timeline(timeline: dict[str, Any]) -> None:
    shots = timeline.get("shots") or []
    if not shots:
        raise ValueError("Master timeline contains no shots")
    cursor = 0.0
    repeated_framing = 0
    previous = None
    for shot in shots:
        start, end = float(shot["start"]), float(shot["end"])
        if abs(start - cursor) > 0.02 or end <= start:
            raise ValueError(f"Shot timeline discontinuity at {shot.get('shot_id')}")
        if abs((end - start) - float(shot["duration"])) > 0.02:
            raise ValueError(f"Shot duration mismatch at {shot.get('shot_id')}")
        narration = shot.get("narration_segment") or {}
        if abs(float(narration.get("start", -1)) - start) > 0.02 or abs(float(narration.get("end", -1)) - end) > 0.02:
            raise ValueError(f"Narration clock mismatch at {shot.get('shot_id')}")
        actions = shot.get("actions") or []
        if any(action in MOTION_ACTIONS for action in actions) and not shot.get("characters"):
            raise ValueError(f"Character action has no character at {shot.get('shot_id')}")
        framing = shot.get("framing")
        repeated_framing = repeated_framing + 1 if framing == previous else 1
        if repeated_framing > 2:
            raise ValueError("More than two consecutive shots use the same framing")
        previous, cursor = framing, end
    if abs(cursor - float(timeline.get("duration", 0))) > 0.02:
        raise ValueError("Timeline duration does not match its final shot")
    cues = timeline.get("tracks", {}).get("subtitles", [])
    narration = timeline.get("tracks", {}).get("narration", [])
    if len(cues) != len(narration) or any(
        abs(float(cue["start"]) - float(event["start"])) > 0.02
        or abs(float(cue["end"]) - float(event["end"])) > 0.02
        for cue, event in zip(cues, narration)
    ):
        raise ValueError("Subtitle and narration timelines are not source-locked")


_FALLBACK_ACTIONS = ("look_around", "look_left", "look_right")


def extract_actions(text: str) -> list[str]:
    """Reflective/expository narration (most documentary biography scripts)
    often contains no locomotion or interaction verb at all. The previous
    single fallback, "observe", is not handled by the character rig's pose
    branches (app/video/illustrated_rig.py) or the camera-choice table
    (_camera_for below), so every such shot rendered with near-zero character
    motion, near-zero environment motion, and only one of two possible camera
    moves - exactly the post-render QA failures this produces. Rotate through
    real, rig-animated actions instead, keyed off the sentence text so
    consecutive fallback shots don't all pick the same one.
    """
    actions = [action for pattern, action in ACTION_PATTERNS if re.search(pattern, text, re.I)]
    if actions:
        return actions
    index = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % len(_FALLBACK_ACTIONS)
    return [_FALLBACK_ACTIONS[index]]


def _primary_action(actions: list[str]) -> str:
    """Prefer the visible interaction when one sentence contains locomotion too."""
    priority = (
        "open_door", "close_door", "pick_up_object", "put_down_object",
        "sit", "stand_up", "stop", "look_around", "look_left", "look_right",
        "enter_room", "exit_room", "walk", "turn_head", "point", "nod", "react",
    )
    return next((action for action in priority if action in actions), actions[0])


def _clean_text(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", text).split()).strip(" ,")


def _framing_for(index: int, previous: str) -> str:
    cycle = ("wide", "medium", "medium", "closeup", "wide", "over_shoulder")
    framing = cycle[(index - 1) % len(cycle)]
    return "closeup" if framing == previous and index % 2 else framing


_CAMERA_CHOICES = {
    "walk": ("tracking", "follow"), "enter_room": ("follow", "tracking"),
    "exit_room": ("follow", "tracking"), "look_left": ("locked_medium", "subtle_orbit"),
    "look_right": ("locked_medium", "subtle_orbit"), "look_around": ("subtle_orbit", "locked_medium"),
    "stop": ("settle", "locked_medium"), "open_door": ("dolly", "tracking"),
}


def _camera_for(action: str, framing: str, shot_id: str = "") -> dict[str, Any]:
    choices = _CAMERA_CHOICES.get(action)
    if choices:
        # Alternate between plausible moves for the same action so a video
        # with many "walk" shots does not repeat one identical camera move.
        index = int(hashlib.sha256(f"{action}|{shot_id}".encode("utf-8")).hexdigest(), 16) % len(choices)
        move = choices[index]
    else:
        move = "locked" if framing == "closeup" else "subtle_dolly"
    return {"move": move, "framing": framing, "motivated_by": action}


def _animation_plan(actions: list[str], actor: str | None, environment: str) -> dict[str, Any]:
    return {
        "character": {
            "required": bool(actor), "rig": "segmented_artwork_2d",
            "motions": actions if actor else [], "camera_motion_excluded_from_score": True,
        },
        "environment": {
            "required": True, "motions": _environment_motions(environment),
        },
        "events": [{"at": 0.08, "action": action} for action in actions],
    }


def _environment_motions(environment: str) -> list[str]:
    lower = environment.lower()
    if "street" in lower:
        return ["traffic_pass", "pedestrian_walk", "shop_fan_rotate", "light_flicker"]
    if "bank" in lower or "room" in lower:
        return ["ceiling_fan_rotate", "papers_shift", "background_people_move"]
    return ["depth_parallax", "atmosphere_drift"]


def _sfx_for(actions: list[str], environment: str) -> list[str]:
    result = []
    if any(action in {"walk", "enter_room", "exit_room"} for action in actions):
        result.append("footsteps")
    if any(action in {"open_door", "close_door", "enter_room", "exit_room"} for action in actions):
        result.append("door")
    if "street" in environment.lower():
        result.append("street_ambience")
    return result


def _timed_sfx(shot: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for index, name in enumerate(shot.get("sound_effects") or []):
        start = round(float(shot["start"]) + min(0.3 + index * 0.25, float(shot["duration"]) * 0.5), 3)
        remaining = max(0.2, float(shot["end"]) - start)
        duration = min(1.2 if name == "door" else remaining, remaining)
        events.append({
            "event_id": f"{shot['shot_id']}_{name}", "shot_id": shot["shot_id"],
            "start": start, "end": round(start + max(0.2, duration), 3),
            "source": name, "volume_db": -15, "fade_in": 0.03, "fade_out": 0.08,
        })
    return events


def _ambience_track(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "event_id": f"A{index:03d}", "shot_id": shot["shot_id"],
        "start": shot["start"], "end": shot["end"], "source": f"{shot['environment']}_ambience",
        "volume_db": -26, "fade_in": 0.15, "fade_out": 0.2,
    } for index, shot in enumerate(shots, 1)]


def _music_track(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not shots:
        return []
    return [{
        "event_id": "M001", "start": 0.0, "end": shots[-1]["end"],
        "source": shots[0]["music"], "volume_db": -24,
        "duck_under": ["narration", "dialogue"], "duck_db": -9,
    }]


def _emotion(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("fear", "danger", "threat")):
        return "concerned"
    if any(word in lower for word in ("look", "wonder", "unclear")):
        return "thoughtful"
    return "serious"
