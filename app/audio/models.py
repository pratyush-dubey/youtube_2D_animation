"""Validated, serializable records for the cinematic audio timeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


AudioType = Literal["voice", "dialogue", "foley", "sfx", "ambience", "music", "silence"]


@dataclass
class AudioEvent:
    audio_id: str
    type: AudioType
    start_time: float
    duration: float
    source: str
    volume_db: float
    pan: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    priority: int = 50
    scene: int | str | None = None
    shot: str | None = None
    character: str | None = None
    emotion: str = "neutral"
    layer: str = ""
    text: str | None = None
    language: str | None = None
    pronunciation: dict[str, Any] = field(default_factory=dict)
    asset_available: bool = False
    sync_action: str | None = None

    def __post_init__(self) -> None:
        self.start_time = round(float(self.start_time), 3)
        self.duration = round(float(self.duration), 3)
        self.volume_db = float(self.volume_db)
        self.pan = float(self.pan)
        if self.start_time < 0 or self.duration <= 0:
            raise ValueError("Audio events require non-negative start and positive duration")
        if not -1 <= self.pan <= 1:
            raise ValueError("Audio pan must be between -1 and 1")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start"] = data.pop("start_time")
        return data


@dataclass
class VoicePack:
    voice_id: str
    name: str
    gender: str
    age_range: str
    accent: str
    language: str
    tone: str
    pitch: float = 0.0
    speaking_rate: float = 1.0
    emotion_profile: dict[str, dict[str, float]] = field(default_factory=dict)
    style: str = "documentary"
    sample_reference: str | None = None
    provider: str = "piper_local"
    provider_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoicePack":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
