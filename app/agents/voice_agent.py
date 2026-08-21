"""
VoiceAgent — generates per-scene narration audio.

Cloud providers (no Ollama):
  1. Google Cloud Text-to-Speech (free tier: 1M chars/month WaveNet, 4M Standard)
  2. ElevenLabs (free tier: 10,000 chars/month)
  3. gTTS (Google Translate TTS — free, reliable, English only for commercial is grey area)
  4. pyttsx3 offline fallback (system TTS, truly free, lower quality)
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings

logger = structlog.get_logger(__name__)


class VoiceAgent(Agent):
    name = "voice_agent"
    max_retries = 2

    def _execute(self, context: AgentContext) -> dict[int, Path]:
        if not context.storyboard:
            raise ValueError("StoryboardAgent must run before VoiceAgent")

        audio_dir = context.output_dir / "audio" / "narration"
        audio_dir.mkdir(parents=True, exist_ok=True)
        narration: dict[int, Path] = {}

        provider = getattr(settings, "tts_provider", "gtts")

        for scene in context.storyboard:
            scene_id = scene["scene_id"]
            text = scene.get("narration", "").strip()
            if not text:
                continue

            out_path = audio_dir / f"scene_{scene_id:03d}.mp3"
            if out_path.exists() and out_path.stat().st_size > 500:
                narration[scene_id] = out_path
                continue

            path = self._synthesize(text, out_path, provider)
            narration[scene_id] = path

        context.narration_files = narration
        logger.info(
            "voice_complete",
            project=context.project_id,
            scenes=len(narration),
            provider=provider,
        )
        return narration

    # ── providers ─────────────────────────────────────────────────────────

    def _synthesize(self, text: str, output_path: Path, provider: str) -> Path:
        if provider == "elevenlabs":
            try:
                return self._elevenlabs(text, output_path)
            except Exception as exc:
                logger.warning("elevenlabs_failed", error=str(exc))

        if provider in ("google_tts", "gtts"):
            try:
                return self._gtts(text, output_path)
            except Exception as exc:
                logger.warning("gtts_failed", error=str(exc))

        # pyttsx3 offline fallback
        try:
            return self._pyttsx3(text, output_path)
        except Exception as exc:
            logger.warning("pyttsx3_failed", error=str(exc))
            output_path.write_bytes(b"")  # empty placeholder
            return output_path

    def _elevenlabs(self, text: str, output_path: Path) -> Path:
        import urllib.request, json as _json
        api_key = getattr(settings, "elevenlabs_api_key", "")
        voice_id = getattr(settings, "elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")
        payload = _json.dumps({
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode()
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            data=payload,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            output_path.write_bytes(resp.read())
        return output_path

    def _gtts(self, text: str, output_path: Path) -> Path:
        from gtts import gTTS
        lang = getattr(settings, "tts_voice", "en")[:2]
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(str(output_path))
        return output_path

    def _pyttsx3(self, text: str, output_path: Path) -> Path:
        import pyttsx3, tempfile, shutil
        engine = pyttsx3.init()
        engine.setProperty("rate", 150)
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        engine.save_to_file(text, str(tmp))
        engine.runAndWait()
        if tmp.exists():
            shutil.move(str(tmp), str(output_path.with_suffix(".wav")))
            # rename to .mp3 for consistency (it's actually WAV but ffmpeg handles it)
            output_path.with_suffix(".wav").rename(output_path)
        return output_path
