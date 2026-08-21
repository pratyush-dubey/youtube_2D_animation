"""Bilingual English/Hindi subtitle writing against the shot timeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    english: str
    hindi: str

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError("Subtitle cue end must follow start")
        if not self.english.strip() or not self.hindi.strip():
            raise ValueError("Both English and Hindi subtitle text are required")


def write_srt(cues: list[SubtitleCue], output_path: Path, language: str) -> Path:
    if language not in {"english", "hindi", "bilingual"}:
        raise ValueError("language must be english, hindi, or bilingual")
    lines = []
    for index, cue in enumerate(cues, 1):
        text = cue.english if language == "english" else cue.hindi
        if language == "bilingual":
            text = cue.english + "\n" + cue.hindi
        lines.extend([str(index), f"{_time(cue.start)} --> {_time(cue.end)}", text, ""])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _time(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
