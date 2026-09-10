"""Typed character identity schema — the single source of truth for one
canonical character. Every downstream asset (reference photo, body-part
PNGs, and eventually the Blender rig) derives from one of these, never from
an independently-invented description.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterSchema(BaseModel):
    character_id: str
    name: str
    age: int | None = None
    gender_presentation: str = ""
    description: str = ""
    face: str = ""
    hair: str = ""
    skin_tone: str = ""
    body: str = ""
    clothing: str = ""
    accessories: str = ""
    palette: str = ""
    art_style: str = "cinematic 2D illustrated documentary"
    reference_image: str = ""
    negative_constraints: list[str] = Field(default_factory=list)

    # Real-person identity references only (see characters/generator/reference.py).
    is_real_person: bool = True
    reference_source_url: str = ""
    reference_file_url: str = ""
    reference_license: str = ""
    reference_artist: str = ""
    reference_attribution: str = ""

    # Reproducibility metadata for whichever provider generated the parts.
    seed: int | None = None
    provider: str = ""

    def appearance_summary(self) -> str:
        """One-line prose summary for prompt-building (see generator/parts.py)."""
        pieces = [
            f"{self.age}-year-old" if self.age else "",
            self.gender_presentation, self.face, self.hair and f"{self.hair} hair",
            self.skin_tone and f"{self.skin_tone} skin", self.body,
        ]
        return ", ".join(p for p in pieces if p).strip()
