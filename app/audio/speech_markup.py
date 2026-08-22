"""Internal speech markup parser shared by every voice provider."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_TAG = re.compile(r"<(/?)([a-z_]+)(?:=([^>]+))?>", re.IGNORECASE)
SUPPORTED_CONTROLS = {"emotion", "pause", "speed", "pitch", "emphasis", "whisper", "volume"}


@dataclass(frozen=True)
class SpeechSegment:
    text: str = ""
    controls: dict[str, str | bool | float] = field(default_factory=dict)
    pause_seconds: float = 0.0


def parse_speech_markup(markup: str) -> list[SpeechSegment]:
    """Parse simple nested tags without exposing provider-specific SSML."""
    segments: list[SpeechSegment] = []
    controls: dict[str, str | bool | float] = {}
    stack: list[tuple[str, str | bool | float | None]] = []
    cursor = 0
    for match in _TAG.finditer(markup):
        text = " ".join(markup[cursor:match.start()].split())
        if text:
            segments.append(SpeechSegment(text=text, controls=dict(controls)))
        closing, key, raw_value = match.groups()
        key = key.lower()
        if key not in SUPPORTED_CONTROLS:
            raise ValueError(f"Unsupported speech control: {key}")
        if closing:
            previous = next((value for name, value in reversed(stack) if name == key), None)
            stack = [(name, value) for name, value in stack if name != key]
            if previous is None:
                controls.pop(key, None)
            else:
                controls[key] = previous
        elif key == "pause":
            seconds = max(0.0, min(float((raw_value or "0").strip()), 5.0))
            segments.append(SpeechSegment(pause_seconds=seconds))
        else:
            previous = controls.get(key)
            stack.append((key, previous))
            value: str | bool | float = (raw_value or True)
            if key in {"speed", "pitch", "volume"}:
                value = float(value)
            controls[key] = value
        cursor = match.end()
    tail = " ".join(markup[cursor:].split())
    if tail:
        segments.append(SpeechSegment(text=tail, controls=dict(controls)))
    return segments


def plain_speech_text(markup: str, pronunciation: dict | None = None) -> str:
    pronunciation = pronunciation or {}
    parts: list[str] = []
    for segment in parse_speech_markup(markup):
        if segment.pause_seconds:
            parts.append(". ")
            continue
        text = segment.text
        for phrase, entry in pronunciation.items():
            replacement = entry.get("phonetic") if isinstance(entry, dict) else str(entry)
            if replacement:
                text = re.sub(re.escape(phrase), replacement, text, flags=re.IGNORECASE)
        if text:
            parts.append(text)
    return " ".join(parts).strip()
