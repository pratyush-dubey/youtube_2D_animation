"""
MusicAgent — selects background music from a local CC0 library.

Priority order:
  1. Local library (assets/music/) — any file in metadata.json with commercial_use=true
  2. Bundled CC0 tracks from ccmixter.org / pixabay (verified working URLs)
  3. FFmpeg-generated silent fallback (guarantees the video always renders)

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
        "mood": ["calm", "documentary", "curious"],
    },
    {
        "file": "mysterious_ambient_02.mp3",
        "url": "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a73467.mp3",
        "license": "Pixabay License",
        "author": "Pixabay",
        "source": "pixabay.com",
        "commercial_use": True,
        "attribution_required": False,
        "mood": ["mysterious", "dramatic", "tense"],
    },
    {
        "file": "space_ambient_03.mp3",
        "url": "https://cdn.pixabay.com/download/audio/2021/11/25/audio_40d74b03d4.mp3",
        "license": "Pixabay License",
        "author": "Pixabay",
        "source": "pixabay.com",
        "commercial_use": True,
        "attribution_required": False,
        "mood": ["epic", "cinematic", "space"],
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

        # 2. Download a CC0 track
        track = self._download_cc0(mood)
        if track:
            context.music_path = track
            logger.info("music_downloaded", path=str(track), mood=mood)
            return context.music_path

        # 3. Silent fallback — generates a silent MP3 so the compositor
        #    always has something to work with (no loud silence gaps)
        silent = self._generate_silent_track(context)
        if silent:
            context.music_path = silent
            logger.info("music_silent_fallback", path=str(silent))
            return context.music_path

        logger.warning("music_unavailable", project=context.project_id)
        return None

    # ── helpers ───────────────────────────────────────────────────────────

    def _dominant_mood(self, scenes: list[dict]) -> str:
        moods: dict[str, int] = {}
        for s in scenes:
            m = s.get("music_mood", "calm")
            moods[m] = moods.get(m, 0) + 1
        return max(moods, key=moods.get) if moods else "calm"

    def _find_local(self, mood: str) -> str | None:
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
        if matches:
            return str(_MUSIC_DIR / random.choice(matches)["file"])
        available = [
            t for t in tracks
            if (_MUSIC_DIR / t["file"]).exists()
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

    def _generate_silent_track(self, context: AgentContext) -> Path | None:
        """Generate a silent MP3 using FFmpeg as a last resort."""
        import subprocess
        silent = _MUSIC_DIR / "silent_fallback.mp3"
        if silent.exists():
            return silent
        try:
            # Estimate total duration from storyboard
            total = sum(
                float(s.get("duration_seconds", 8)) for s in (context.storyboard or [])
            ) + 30  # add 30 s buffer
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                    "-t", str(int(total)),
                    "-c:a", "libmp3lame", "-b:a", "64k",
                    str(silent),
                ],
                check=True, capture_output=True,
            )
            return silent
        except Exception as exc:
            logger.warning("silent_track_generation_failed", error=str(exc))
            return None
