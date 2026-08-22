"""VoicePack loading, validation and language-aware narrator selection."""
from __future__ import annotations

import json
from pathlib import Path

from app.audio.models import VoicePack


DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "voicepacks"
LANGUAGE_FOLDERS = {"english": "english", "en": "english", "hindi": "hindi", "hi": "hindi", "kannada": "kannada", "kn": "kannada"}


class VoicePackRegistry:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = root

    def list(self, language: str | None = None) -> list[VoicePack]:
        base = self.root
        if language:
            base = base / LANGUAGE_FOLDERS.get(language.lower(), language.lower())
        if not base.exists():
            return []
        packs: list[VoicePack] = []
        for path in sorted(base.rglob("voicepack.json")):
            packs.append(VoicePack.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return packs

    def get(self, voice_id: str, language: str | None = None) -> VoicePack:
        matches = [pack for pack in self.list(language) if pack.voice_id == voice_id]
        if len(matches) != 1:
            raise LookupError(f"Expected one VoicePack {voice_id!r}; found {len(matches)}")
        return matches[0]

    def narrator(self, language: str) -> VoicePack:
        packs = [pack for pack in self.list(language) if pack.style == "documentary"]
        if not packs:
            raise LookupError(f"No documentary narrator VoicePack is configured for {language}")
        return packs[0]
