"""Deterministic per-shot character blocking (start/end screen position).

Without this, every scene that shares an action ends up sliding a character
along the exact same path, which reads as a cardboard cutout being dragged
across the frame. Position instead varies with action, framing, and a
scene-specific seed, so no two shots trace the same path unless the
underlying narration and staging genuinely repeat.
"""
from __future__ import annotations

import hashlib

STATIC_ACTIONS = {
    "react", "look_around", "look_left", "look_right", "turn_head", "scan",
    "sit", "stand_up", "nod", "point", "observe", "idle", "neutral",
}
CROSSING_ACTIONS = {
    "walk", "walking", "run", "walk_across", "enter", "enter_room",
    "exit_room", "environment_activity",
}

_SPAN_BY_FRAMING = {
    "wide": 0.58, "medium": 0.46, "insert": 0.34, "rear": 0.5, "over_shoulder": 0.4,
}


def character_blocking(action: str, framing: str, seed: int) -> dict:
    """Return normalised (0..1 of frame width) start/end x position for a shot."""
    action = str(action or "react").lower()
    framing = str(framing or "medium").lower()
    digest = hashlib.sha256(f"{action}|{framing}|{seed}".encode("utf-8")).digest()
    jitter = (digest[0] / 255.0 - 0.5) * 0.10
    direction = 1.0 if digest[1] % 2 == 0 else -1.0

    if framing == "closeup":
        center = 0.56 + jitter * 0.4
        return {"start_x": center, "end_x": center}

    if action in CROSSING_ACTIONS:
        span = _SPAN_BY_FRAMING.get(framing, 0.46)
        center = 0.5 + jitter
        half = span / 2.0
        start_x = max(0.08, min(0.92, center - direction * half))
        end_x = max(0.08, min(0.92, center + direction * half))
        return {"start_x": round(start_x, 4), "end_x": round(end_x, 4)}

    if action == "stop":
        center = 0.5 + jitter
        return {"start_x": max(0.1, center - 0.06), "end_x": min(0.9, center + 0.03)}

    center = 0.56 + jitter
    return {"start_x": center, "end_x": center}
