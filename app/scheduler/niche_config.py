"""
Niche configuration for the autonomous scheduler.

A "niche" defines the type of content the channel produces.
Each niche has:
  - A topic domain (used by TrendAgent to find trending ideas)
  - Style presets (visual and script style)
  - Target duration
  - Language
  - Upload privacy (always default private; human approves)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NicheConfig:
    """Configuration for a single YouTube channel niche."""

    niche: str = "science and technology"
    style: str = "documentary"
    language: str = "English"
    target_duration_seconds: int = 480
    aspect_ratio: str = "16:9"
    # Extra instructions given to the LLM for script generation
    tone_notes: str = "Factual, engaging, suitable for a general audience."
    # Whether to automatically attempt YouTube upload when rendering completes
    upload_after_render: bool = False
    # Tags to always append regardless of topic
    base_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "niche": self.niche,
            "style": self.style,
            "language": self.language,
            "target_duration_seconds": self.target_duration_seconds,
            "aspect_ratio": self.aspect_ratio,
            "tone_notes": self.tone_notes,
            "upload_after_render": self.upload_after_render,
            "base_tags": self.base_tags,
        }


# ── Preset library ──────────────────────────────────────────────────────────
#
# Add your own niches here or override via settings / environment.
#
PRESET_NICHES: dict[str, NicheConfig] = {
    "science": NicheConfig(
        niche="science and technology",
        style="documentary",
        language="English",
        target_duration_seconds=480,
        tone_notes="Factual, awe-inspiring. Targeted at curious adults.",
        base_tags=["science", "technology", "documentary", "education"],
    ),
    "history": NicheConfig(
        niche="world history mysteries",
        style="documentary",
        language="English",
        target_duration_seconds=600,
        tone_notes="Story-driven, dramatic. Like a history channel special.",
        base_tags=["history", "mysteries", "ancient", "documentary"],
    ),
    "space": NicheConfig(
        niche="space exploration and astronomy",
        style="cinematic",
        language="English",
        target_duration_seconds=480,
        tone_notes="Epic, awe-inspiring. Think NASA narration style.",
        base_tags=["space", "NASA", "astronomy", "universe", "cosmos"],
    ),
    "psychology": NicheConfig(
        niche="psychology and human behavior",
        style="educational",
        language="English",
        target_duration_seconds=420,
        tone_notes="Accessible, relatable. Based on peer-reviewed research.",
        base_tags=["psychology", "behavior", "mind", "science"],
    ),
    "tech": NicheConfig(
        niche="artificial intelligence and future technology",
        style="explainer",
        language="English",
        target_duration_seconds=420,
        tone_notes="Clear, enthusiastic but measured. Balanced on hype vs reality.",
        base_tags=["AI", "technology", "future", "machine learning"],
    ),
}


def get_niche_config(name: str) -> NicheConfig:
    """
    Return a NicheConfig by preset name.
    Falls back to a generic config built from the raw niche string
    if the name doesn't match a preset.
    """
    if name in PRESET_NICHES:
        return PRESET_NICHES[name]
    # Treat the name itself as the niche topic string
    return NicheConfig(niche=name)
