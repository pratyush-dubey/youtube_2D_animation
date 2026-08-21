"""
Pydantic schemas for SEO metadata output validation.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class TitleCandidate(BaseModel):
    title: str
    curiosity_score: int = Field(default=5, ge=1, le=10)
    clarity_score: int = Field(default=5, ge=1, le=10)
    keyword_score: int = Field(default=5, ge=1, le=10)
    ctr_score: int = Field(default=5, ge=1, le=10)
    total_score: int = Field(default=20, ge=0, le=40)
    reason: str = ""

    @field_validator("total_score", mode="before")
    @classmethod
    def _compute_total(cls, v: Any) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 20


class Chapter(BaseModel):
    time: str          # "0:00"
    label: str


class SEOMetadata(BaseModel):
    title_candidates: list[TitleCandidate] = Field(default_factory=list)
    best_title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    category: str = "Science & Technology"
    default_language: str = "en"

    @field_validator("tags", "hashtags", "chapters", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list:
        if v is None:
            return []
        return v

    @field_validator("best_title", mode="before")
    @classmethod
    def _fallback_title(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return "Untitled Video"
        return str(v)[:100]

    def best_tags_str(self) -> str:
        """Comma-separated tags string for YouTube API."""
        return ",".join(self.tags[:25])

    def description_with_chapters(self) -> str:
        """Full description with chapters block injected."""
        return self.description
