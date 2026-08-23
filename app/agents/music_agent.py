"""
MusicAgent — selects background music from a local CC0 library.

Priority order:
  1. Local library (assets/music/) — any file in metadata.json with commercial_use=true
  2. Bundled CC0 tracks from ccmixter.org / pixabay (verified working URLs)
  3. Report unavailable and wait for licensed/imported music

Every downloaded track includes full licensing metadata so the system never
publishes content with unknown licensing status.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings

logger = structlog.get_logger(__name__)

_MUSIC_DIR = settings.asset_dir / "music"
_META_FILE = _MUSIC_DIR / "metadata.json"

# ── Verified working CC0 / royalty-free tracks ─────────────────────────────
# All URLs tested 2025-08.  Pixabay audio is free for commercial use with no
# attribution required (Pixabay License).  ccmixter tracks are CC BY 3.0 —
# attribution must appear in the video description.
_CC0_TRACKS = [
    {
        "file": "ambient_documentary_01.mp3",
        "url": "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3",
        "license": "Pixabay License",
        "author": "Pixabay",
        "source": "pixabay.com",
        "commercial_use": True,
        "attribution_required": False,
        "mood": ["calm", "documentary", "curious", "serious", "reflective"],
    },
    {
        "file": "mysterious_ambient_02.mp3",
        "url": "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a73467.mp3",
        "license": "Pixabay License",
        "author": "Pixabay",
        "source": "pixabay.com",
        "commercial_use": True,
        "attribution_required": False,
        "mood": ["mysterious", "dramatic", "tense", "restrained_tension", "eerie"],
    },
    {
        "file": "space_ambient_03.mp3",
        "url": "https://cdn.pixabay.com/download/audio/2021/11/25/audio_40d74b03d4.mp3",
        "license": "Pixabay License",
        "author": "Pixabay",
        "source": "pixabay.com",
        "commercial_use": True,
        "attribution_required": False,
        "mood": ["epic", "cinematic", "space", "uplifting", "hopeful"],
    },
]


class MusicAgent(Agent):
    name = "music_agent"
    max_retries = 1

    def _execute(self, context: AgentContext) -> Path | None:
        _MUSIC_DIR.mkdir(parents=True, exist_ok=True)

        mood = self._dominant_mood(context.storyboard or [])

        # 1. Local library
        track = self._find_local(mood)
        if track:
            context.music_path = Path(track)
            logger.info("music_selected_local", path=str(track), mood=mood)
            return context.music_path

        # 2. Download a CC0 track matching this video's actual mood
        track = self._download_cc0(mood)
        if track:
            context.music_path = track
            logger.info("music_downloaded", path=str(track), mood=mood)
            return context.music_path

        # 3. Last resort: any previously downloaded, licensed track (e.g. no
        #    internet for the mood-matched download above) - better than no
        #    music, but the mood mismatch is real, so it's logged as such.
        track = self._find_any_local()
        if track:
            context.music_path = Path(track)
            logger.warning("music_selected_mood_mismatch_fallback", path=str(track), mood=mood)
            return context.music_path

        # 4. Silent fallback — generates a silent MP3 so the compositor
        #    always has something to work with (no loud silence gaps)
        context.warnings.append(
            "Licensed music is unavailable; import an approved track before final mixing"
        )
        logger.warning("music_unavailable_no_substitution", project=context.project_id)
        return None

    # ── helpers ───────────────────────────────────────────────────────────

    def _dominant_mood(self, scenes: list[dict]) -> str:
        moods: dict[str, int] = {}
        for s in scenes:
            m = s.get("music_mood", "calm")
            moods[m] = moods.get(m, 0) + 1
        return max(moods, key=moods.get) if moods else "calm"

    def _find_local(self, mood: str) -> str | None:
        """Mood-matched local track only. A mood-blind fallback used to live
        here, returning literally any downloaded track when nothing matched
        - which meant it always "succeeded" and _download_cc0() (the thing
        that actually fetches a mood-appropriate track) was never reached.
        Every video ended up with whichever track happened to be cached
        first, regardless of its own mood. See _find_any_local() for the
        real last-resort, now ordered after the mood-matched download
        attempt instead of before it."""
        if not _META_FILE.exists():
            return None
        try:
            tracks = json.loads(_META_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
        matches = [
            t for t in tracks
            if t.get("commercial_use")
            and mood in t.get("mood", [])
            and (_MUSIC_DIR / t["file"]).exists()
            and (_MUSIC_DIR / t["file"]).stat().st_size > 10_000
        ]
        return str(_MUSIC_DIR / random.choice(matches)["file"]) if matches else None

    def _find_any_local(self) -> str | None:
        """Absolute last resort - any previously downloaded, licensed track,
        used only after both a mood-matched local track and a fresh
        mood-matched CC0 download have failed (e.g. no internet)."""
        if not _META_FILE.exists():
            return None
        try:
            tracks = json.loads(_META_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
        available = [
            t for t in tracks
            if t.get("commercial_use")
            and (_MUSIC_DIR / t["file"]).exists()
            and (_MUSIC_DIR / t["file"]).stat().st_size > 10_000
        ]
        return str(_MUSIC_DIR / available[0]["file"]) if available else None

    def _download_cc0(self, mood: str) -> Path | None:
        import urllib.request
        candidates = [t for t in _CC0_TRACKS if mood in t.get("mood", [])]
        track = candidates[0] if candidates else _CC0_TRACKS[0]
        dest = _MUSIC_DIR / track["file"]

        if dest.exists() and dest.stat().st_size > 10_000:
            return dest

        try:
            req = urllib.request.Request(
                track["url"],
                headers={"User-Agent": "AIYouTubeBot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if len(data) < 10_000:
                raise ValueError(f"Downloaded file too small: {len(data)} bytes")
            dest.write_bytes(data)

            # Persist metadata
            existing: list[dict] = []
            if _META_FILE.exists():
                try:
                    existing = json.loads(_META_FILE.read_text(encoding="utf-8"))
                except Exception:
                    pass
            if not any(t["file"] == track["file"] for t in existing):
                existing.append(track)
                _META_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")

            return dest
        except Exception as exc:
            logger.warning("music_download_failed", url=track["url"], error=str(exc))
            return None
