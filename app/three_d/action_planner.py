"""Deterministic narration-to-action planning with emotion-driven behavior."""
from __future__ import annotations

import re


class ActionPlanner:
    _patterns = (
        (r"\bwalk(?:ed|s|ing)?\b", "walk"),
        (r"\bturn(?:ed|s|ing)?\b|look(?:ed|s|ing)? back", "turn"),
        (r"\bsit(?:s|ting)?\b|sat\b", "sit"),
        (r"\bspeak(?:s|ing)?\b|said\b|talk(?:s|ed|ing)?\b", "talk"),
        (r"\breach(?:es|ed|ing)?\b", "reach"),
        (r"\bopen(?:s|ed|ing)?\b", "open"),
        (r"\blook(?:s|ed|ing)?\b", "look"),
    )

    def plan(self, narration: str, duration: float, emotion: str = "neutral") -> list[dict]:
        text = narration.lower()
        names = [name for pattern, name in self._patterns if re.search(pattern, text)] or ["idle"]
        slot = max(0.4, duration / len(names))
        return [
            {
                "action": name,
                "start": round(index * slot, 3),
                "duration": round(slot, 3),
                "emotion": emotion,
                "blend_in": 0.25,
                "blend_out": 0.25,
            }
            for index, name in enumerate(names)
        ]
