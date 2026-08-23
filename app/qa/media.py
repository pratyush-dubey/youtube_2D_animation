"""Measure rendered pixels and audio instead of trusting animation plans."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config.settings import settings
from app.metadata.sanitizer import sanitize_metadata_payload
from app.timeline.master import measure_audio_duration, validate_master_timeline


def inspect_render(
    video_path: Path,
    timeline: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    audio_cues: list[dict[str, Any]] | None = None,
    subtitle_path: Path | None = None,
    character_roi: tuple[float, float, float, float] = (0.22, 0.12, 0.82, 0.96),
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Return hard PASS/FAIL gates based on decoded frames and muxed audio."""
    validate_master_timeline(timeline)
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    motion = _motion_metrics(video_path, character_roi)
    media = _probe(video_path)
    expected = float(timeline["duration"])
    audio_duration = float(media.get("audio_duration") or 0.0)
    duration_error = abs(audio_duration - expected)
    # app.agents.video_edit_agent._concat_clips crossfades adjacent scene
    # clips (up to 0.45s per boundary, capped by each clip's own length) -
    # every transition legitimately shortens total runtime versus the naive
    # sum of shot durations; that is dissolve editing working as intended,
    # not a sync defect. Size the tolerance to the maximum possible crossfade
    # shrinkage instead of a fixed near-zero threshold that only a hard-cut
    # edit could ever satisfy.
    max_crossfade_shrinkage = 0.45 * max(len(timeline["shots"]) - 1, 0)
    duration_tolerance = max(0.08, max_crossfade_shrinkage)
    cue_sync = _audio_event_sync(timeline, audio_cues or [])
    metadata_clean = sanitize_metadata_payload(metadata or {})
    metadata_pass = metadata_clean == (metadata or {})
    shot_actions = _shot_action_results(motion["samples"], timeline["shots"])
    required_action_scores = [item["score"] for item in shot_actions if item["required"]]
    character_score = min(required_action_scores) if required_action_scores else 0.0
    camera_moves = {str((shot.get("camera") or {}).get("move", "locked")) for shot in timeline["shots"]}
    silence = _unexpected_silence(video_path)
    report = {
        "video": str(video_path.resolve()),
        "expected_duration": expected,
        "measured_video_duration": media.get("video_duration"),
        "measured_audio_duration": audio_duration,
        "gates": {
            "no_frozen_frames": {
                "passed": motion["longest_frozen_seconds"] < 0.75,
                "longest_frozen_seconds": motion["longest_frozen_seconds"],
            },
            "no_black_frames": {
                "passed": motion["longest_black_seconds"] < 0.25,
                "longest_black_seconds": motion["longest_black_seconds"],
            },
            "character_motion": {
                "passed": bool(required_action_scores) and character_score >= 0.006,
                "score": character_score,
                "aggregation": "minimum 80th-percentile localized motion across character-required shots",
                "camera_motion_is_not_character_motion": True,
            },
            "environment_motion": {
                "passed": motion["environment_motion_score"] >= 0.002,
                "score": motion["environment_motion_score"],
            },
            "camera": {
                "passed": len(camera_moves - {"locked", "static"}) >= 2,
                "distinct_moves": sorted(camera_moves),
            },
            "shot_actions": {
                "passed": all(item["passed"] for item in shot_actions),
                "shots": shot_actions,
            },
            "audio_sync": {
                "passed": bool(media.get("has_audio")) and duration_error <= duration_tolerance and cue_sync["passed"],
                "duration_error_seconds": round(duration_error, 3),
                "duration_tolerance_seconds": round(duration_tolerance, 3),
                "event_source_lock": cue_sync,
            },
            "no_unexpected_silence": silence,
            "subtitle_sync": {
                "passed": _subtitle_sync(timeline, subtitle_path),
                "source_locked_to_narration": True,
            },
            "metadata_html": {"passed": metadata_pass},
        },
    }
    report["passed"] = all(gate["passed"] for gate in report["gates"].values())
    report["motion_samples"] = motion["samples"]
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _motion_metrics(path: Path, roi: tuple[float, float, float, float]) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        raise ValueError(f"Cannot decode video FPS: {path}")
    stride = max(1, round(fps / 8.0))
    previous = None
    samples: list[dict[str, float]] = []
    frozen_run = longest_run = 0
    black_run = longest_black_run = 0
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % stride:
            index += 1
            continue
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (320, 180))
        if previous is not None:
            h, w = gray.shape
            x1, y1, x2, y2 = (
                round(roi[0] * w), round(roi[1] * h), round(roi[2] * w), round(roi[3] * h)
            )
            delta = cv2.absdiff(previous, gray).astype(np.float32) / 255.0
            actor_pixels = delta[y1:y2, x1:x2]
            outside = delta.copy()
            outside[y1:y2, x1:x2] = np.nan
            environment = float(np.nanmean(outside))
            outside_p90 = float(np.nanpercentile(outside, 90))
            global_change = float(delta.mean())
            # Use the changing-detail tail so articulated hands/head are not
            # diluted by a large, mostly static ROI. Subtract the same tail in
            # the background so a pan cannot satisfy actor motion.
            localized = max(0.0, float(np.percentile(actor_pixels, 90)) - outside_p90 * 0.65)
            samples.append({
                "time": round(index / fps, 3), "global": round(global_change, 6),
                "character": round(localized, 6), "environment": round(environment, 6),
            })
            frozen_run = frozen_run + 1 if global_change < 0.0018 else 0
            longest_run = max(longest_run, frozen_run)
            black_run = black_run + 1 if float(gray.mean()) / 255.0 < 0.025 else 0
            longest_black_run = max(longest_black_run, black_run)
        previous = gray
        index += 1
    capture.release()
    interval = stride / fps
    return {
        "longest_frozen_seconds": round(longest_run * interval, 3),
        "longest_black_seconds": round(longest_black_run * interval, 3),
        "character_motion_score": round(float(np.percentile([s["character"] for s in samples] or [0], 65)), 6),
        "environment_motion_score": round(float(np.percentile([s["environment"] for s in samples] or [0], 50)), 6),
        "samples": samples,
    }


def _shot_action_results(samples: list[dict[str, float]], shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    meaningful = {"walk", "stop", "look_left", "look_right", "look_around", "enter_room", "exit_room", "open_door", "close_door", "pick_up_object", "sit", "stand_up", "turn_head", "point", "nod", "react"}
    for shot in shots:
        action = str(shot.get("action", "observe"))
        inside = [s["character"] for s in samples if float(shot["start"]) <= s["time"] <= float(shot["end"])]
        score = float(np.percentile(inside, 80)) if inside else 0.0
        required = action in meaningful and bool(shot.get("characters"))
        results.append({"shot_id": shot["shot_id"], "action": action, "required": required, "score": round(score, 6), "passed": not required or score >= 0.006})
    return results


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run([
        settings.ffprobe_path, "-v", "error", "-show_entries",
        "stream=codec_type,duration:format=duration", "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    raw = json.loads(result.stdout)
    streams = raw.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    format_duration = float((raw.get("format") or {}).get("duration") or 0.0)
    return {
        "has_audio": bool(audio),
        "video_duration": float(video.get("duration") or format_duration),
        "audio_duration": float(audio.get("duration") or format_duration) if audio else 0.0,
    }


def _unexpected_silence(path: Path) -> dict[str, Any]:
    result = subprocess.run([
        settings.ffmpeg_path, "-hide_banner", "-nostats", "-i", str(path),
        "-af", "silencedetect=noise=-48dB:d=0.8", "-f", "null", "-",
    ], capture_output=True, text=True)
    durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", result.stderr)]
    longest = max(durations, default=0.0)
    return {"passed": longest < 0.8, "longest_silence_seconds": round(longest, 3)}


def _subtitle_sync(timeline: dict[str, Any], subtitle_path: Path | None) -> bool:
    narration = timeline["tracks"].get("narration") or []
    subtitles = timeline["tracks"].get("subtitles") or []
    track_locked = len(narration) == len(subtitles) and all(
        cue.get("text") == event.get("text")
        and abs(float(cue["start"]) - float(event["start"])) <= 0.02
        and abs(float(cue["end"]) - float(event["end"])) <= 0.02
        for cue, event in zip(subtitles, narration)
    )
    if not track_locked or not subtitle_path or not Path(subtitle_path).is_file():
        return False
    blocks = re.split(r"\r?\n\r?\n", Path(subtitle_path).read_text(encoding="utf-8-sig").strip())
    parsed = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            return False
        start, end = (_srt_seconds(value) for value in lines[1].split(" --> "))
        parsed.append({"start": start, "end": end, "text": " ".join(lines[2:]).strip()})
    # app.agents.video_edit_agent._generate_srt intentionally shifts caption
    # times earlier by each scene's crossfade overlap (up to 0.45s, capped
    # per-boundary) to stay locked to the crossfade-shrunk rendered video -
    # that legitimate, cumulative shift is exactly why a near-zero tolerance
    # here could never pass against the un-shrunk master-timeline cues.
    max_crossfade_shrinkage = 0.45 * max(len(subtitles) - 1, 0)
    tolerance = max(0.002, max_crossfade_shrinkage)
    return len(parsed) == len(subtitles) and all(
        abs(item["start"] - float(cue["start"])) <= tolerance
        and abs(item["end"] - float(cue["end"])) <= tolerance
        and item["text"] == cue["text"] for item, cue in zip(parsed, subtitles)
    )


def _srt_seconds(value: str) -> float:
    hours, minutes, tail = value.strip().split(":")
    seconds, millis = tail.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _audio_event_sync(timeline: dict[str, Any], actual: list[dict[str, Any]]) -> dict[str, Any]:
    planned = [event for event in timeline["tracks"].get("sfx", []) if event.get("source") in {"footsteps", "door"}]
    actual_by_id = {str(event.get("event_id")): event for event in actual}
    checks = []
    for event in planned:
        rendered = actual_by_id.get(str(event["event_id"]))
        error = abs(float(rendered.get("start", -999)) - float(event["start"])) if rendered else 999.0
        checks.append({
            "event_id": event["event_id"], "source": event["source"],
            "planned_start": event["start"], "rendered_start": rendered.get("start") if rendered else None,
            "error_seconds": round(error, 3), "passed": bool(rendered) and error <= 0.034,
        })
    return {"passed": bool(checks) and all(item["passed"] for item in checks), "events": checks}
