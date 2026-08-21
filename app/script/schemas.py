"""
Pydantic schemas for script output validation.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ScriptSection(BaseModel):
    id: int
    title: str = ""
    narration: str
    duration_seconds: float = Field(default=30.0, gt=0)
    key_facts: list[str] = Field(default_factory=list)

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def _coerce_duration(cls, v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 30.0


class ScriptResult(BaseModel):
    title: str
    hook: str
    sections: list[ScriptSection] = Field(default_factory=list)
    conclusion: str = ""
    call_to_action: str = ""
    estimated_duration_seconds: int = 480
    word_count: int = 0
    tone: str = "documentary"

    @field_validator("estimated_duration_seconds", mode="before")
    @classmethod
    def _coerce_duration(cls, v: Any) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 480

    @field_validator("word_count", mode="before")
    @classmethod
    def _coerce_words(cls, v: Any) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def full_narration(self) -> str:
        """Concatenate all narration parts for TTS or analysis."""
        parts = [self.hook]
        for s in self.sections:
            parts.append(s.narration)
        if self.conclusion:
            parts.append(self.conclusion)
        if self.call_to_action:
            parts.append(self.call_to_action)
        return "\n\n".join(p for p in parts if p)
