"""
VoiceAgent — generates per-scene narration audio.

Cloud providers (no Ollama):
  1. Google Cloud Text-to-Speech (free tier: 1M chars/month WaveNet, 4M Standard)
  2. ElevenLabs (free tier: 10,000 chars/month)
  3. gTTS (Google Translate TTS — free, reliable, English only for commercial is grey area)
  4. pyttsx3 offline fallback (system TTS, truly free, lower quality)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import structlog

from app.agents.base import Agent, AgentContext
from app.audio.speech_markup import plain_speech_text
from app.audio.voice_provider import create_local_voice_provider
from app.audio.voicepacks import VoicePackRegistry
from app.config.settings import settings

logger = structlog.get_logger(__name__)


class VoiceAgent(Agent):
    name = "voice_agent"
    max_retries = 2

    def _execute(self, context: AgentContext) -> dict[int, Path]:
        sources = list(context.storyboard or _script_narration_sources(context.script))
        if not sources:
            raise ValueError("ScriptAgent must run before VoiceAgent")

        audio_dir = context.output_dir / "audio" / "narration"
        audio_dir.mkdir(parents=True, exist_ok=True)
        narration: dict[int, Path] = {}
        manifest_path = audio_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

        provider = getattr(settings, "tts_provider", "piper")
        voicepack = VoicePackRegistry().narrator(context.language)
        self._voicepack = voicepack
        pronunciation_path = context.output_dir / "audio" / "pronunciation_dictionary.json"
        try:
            pronunciation = json.loads(pronunciation_path.read_text(encoding="utf-8"))
        except Exception:
            pronunciation = {}

        total_scenes = len(sources)
        for scene_index, scene in enumerate(sources):
            scene_id = scene["scene_id"]
            text = scene.get("narration", "").strip()
            if not text:
                continue

            profile = _delivery_profile(
                scene,
                scene_index=scene_index,
                total_scenes=total_scenes,
                base_speed=float(getattr(settings, "tts_speed", 1.10)),
            )

            planned = next((
                event for event in context.audio_plan.get("events", [])
                if event.get("type") == "voice" and str(event.get("scene")) == str(scene_id)
            ), None)
            markup = planned.get("text") if planned else f"<emotion={profile['mood']}>{text}</emotion>"
            out_path = audio_dir / f"scene_{scene_id:03d}{'.wav' if provider == 'piper' else '.mp3'}"
            voice_key = (
                f"voicepack-v1:{provider}:{voicepack.voice_id}:"
                f"{json.dumps(profile, sort_keys=True)}:{json.dumps(pronunciation, sort_keys=True)}:{markup}"
            )
            voice_hash = hashlib.sha256(voice_key.encode("utf-8")).hexdigest()[:16]
            if (
                out_path.exists()
                and out_path.stat().st_size > 500
                and manifest.get(str(scene_id)) == voice_hash
            ):
                narration[scene_id] = out_path
                continue

            path = self._synthesize(markup, out_path, provider, profile, pronunciation)
            path = self._master_voice(path, profile)
            narration[scene_id] = path
            manifest[str(scene_id)] = voice_hash

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        context.narration_files = narration
        from app.timeline.master import measure_audio_duration
        cursor = 0.0
        alignment = []
        for scene in sources:
            scene_id = int(scene["scene_id"])
            path = narration.get(scene_id)
            if not path:
                continue
            duration = measure_audio_duration(path)
            alignment.append({
                "segment_id": f"N{scene_id:03d}", "scene_id": scene_id,
                "start": round(cursor, 3), "end": round(cursor + duration, 3),
                "duration": duration, "text": str(scene.get("narration", "")).strip(),
                "audio_path": str(path.resolve()), "source": "measured_tts_segment",
            })
            scene["duration_seconds"] = duration
            cursor += duration
        context.narration_alignment = alignment
        if not context.storyboard:
            context.storyboard = sources
        (context.output_dir / "narration_alignment.json").write_text(
            json.dumps({"clock": "measured_tts_segments", "duration": round(cursor, 3), "segments": alignment}, indent=2),
            encoding="utf-8",
        )
        _concat_narration(context.output_dir, [narration[int(item["scene_id"])] for item in alignment])
        logger.info(
            "voice_complete",
            project=context.project_id,
            scenes=len(narration),
            provider=provider,
        )
        return narration

    # ── providers ─────────────────────────────────────────────────────────

    def _synthesize(
        self, text: str, output_path: Path, provider: str,
        profile: dict | None = None, pronunciation: dict | None = None,
    ) -> Path:
        if provider == "piper":
            local = create_local_voice_provider(self._voicepack)
            return local.generate_speech(text, self._voicepack, output_path, pronunciation)
        if provider == "edge_tts":
            return self._edge_tts(text, output_path, profile)

        if provider == "elevenlabs":
            return self._elevenlabs(plain_speech_text(text, pronunciation), output_path)

        if provider in ("google_tts", "gtts"):
            return self._gtts(plain_speech_text(text, pronunciation), output_path)
        if provider == "pyttsx3":
            return self._pyttsx3(plain_speech_text(text, pronunciation), output_path)
        raise ValueError(f"Unsupported TTS provider: {provider}")

    def _edge_tts(
        self, text: str, output_path: Path, profile: dict | None = None
    ) -> Path:
        """Generate neural narration using a scene-specific emotional profile."""
        import edge_tts

        configured = str(getattr(settings, "tts_voice", "")).strip()
        voice = configured if "Neural" in configured else "en-IN-PrabhatNeural"
        profile = profile or _delivery_profile(
            {}, 0, 1, float(getattr(settings, "tts_speed", 1.10))
        )
        rate = f"{round((float(profile['rate']) - 1.0) * 100):+d}%"

        async def _save() -> None:
            communicate = edge_tts.Communicate(
                text=_spoken_text(plain_speech_text(text), str(profile.get("mood", "serious"))),
                voice=voice,
                rate=rate,
                pitch=f"{int(profile['pitch_hz']):+d}Hz",
                volume=f"{int(profile['volume_percent']):+d}%",
            )
            await communicate.save(str(output_path))

        asyncio.run(_save())
        if not output_path.exists() or output_path.stat().st_size < 500:
            raise RuntimeError("Edge TTS returned no usable audio")
        return output_path

    def _master_voice(self, path: Path, profile: dict) -> Path:
        """Tighten pauses and add broadcast presence without clipping emotion."""
        if not path.exists() or path.stat().st_size < 500:
            return path
        mastered = path.with_name(f"{path.stem}.master{path.suffix}")
        tempo = float(profile.get("post_tempo", 1.0))
        filters = [
            "silenceremove=start_periods=1:start_duration=0.04:start_threshold=-48dB",
            "areverse",
            "silenceremove=start_periods=1:start_duration=0.12:start_threshold=-48dB",
            "areverse",
        ]
        if abs(tempo - 1.0) > 0.005:
            filters.append(f"atempo={tempo:.3f}")
        filters.extend([
            "highpass=f=75",
            "lowpass=f=13000",
            "acompressor=threshold=0.12:ratio=2.4:attack=8:release=140:makeup=1.35",
            "loudnorm=I=-16:TP=-1.5:LRA=7",
        ])
        try:
            codec_args = ["-codec:a", "pcm_s16le"] if path.suffix.lower() == ".wav" else ["-codec:a", "libmp3lame", "-b:a", "128k"]
            subprocess.run(
                [
                    settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(path), "-af", ",".join(filters),
                    *codec_args, str(mastered),
                ],
                check=True, capture_output=True, text=True,
            )
            if mastered.exists() and mastered.stat().st_size > 500:
                mastered.replace(path)
        except Exception as exc:
            logger.warning("voice_mastering_failed", error=str(exc))
        finally:
            if mastered.exists():
                mastered.unlink()
        return path

    def _elevenlabs(self, text: str, output_path: Path) -> Path:
        import urllib.request, json as _json
        api_key = getattr(settings, "elevenlabs_api_key", "")
        voice_id = getattr(settings, "elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")
        payload = _json.dumps({
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.32,
                "similarity_boost": 0.82,
                "style": 0.48,
                "use_speaker_boost": True,
            },
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
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 150)
        wav = output_path.with_suffix(".wav")
        engine.save_to_file(text, str(wav))
        engine.runAndWait()
        if not wav.exists() or wav.stat().st_size < 1000:
            raise RuntimeError("pyttsx3 returned no usable WAV")
        return wav


_MOOD_DELIVERY = {
    "tense": {"speed": 0.07, "pitch": 1, "volume": 4},
    "dramatic": {"speed": 0.055, "pitch": -1, "volume": 4},
    "mysterious": {"speed": 0.025, "pitch": -3, "volume": 2},
    "eerie": {"speed": 0.015, "pitch": -5, "volume": 1},
    "curious": {"speed": 0.045, "pitch": 2, "volume": 2},
    "uplifting": {"speed": 0.075, "pitch": 3, "volume": 3},
    "hopeful": {"speed": 0.055, "pitch": 2, "volume": 2},
    "serious": {"speed": 0.035, "pitch": -2, "volume": 2},
    "calm": {"speed": 0.0, "pitch": -1, "volume": 0},
}


def _delivery_profile(
    scene: dict, scene_index: int, total_scenes: int, base_speed: float
) -> dict:
    mood = str(scene.get("voice_emotion") or scene.get("music_mood") or "serious").lower()
    tuning = _MOOD_DELIVERY.get(mood, _MOOD_DELIVERY["serious"])
    intensity = str(scene.get("motion_intensity", "medium")).lower()
    intensity_boost = {"low": -0.01, "medium": 0.0, "high": 0.025}.get(intensity, 0.0)
    hook_boost = 0.035 if scene_index == 0 else 0.0
    conclusion_boost = 0.015 if total_scenes > 1 and scene_index == total_scenes - 1 else 0.0
    rate = min(max(base_speed + tuning["speed"] + intensity_boost + hook_boost + conclusion_boost, 0.92), 1.24)
    return {
        "mood": mood,
        "rate": round(rate, 3),
        "pitch_hz": tuning["pitch"],
        "volume_percent": tuning["volume"],
        "post_tempo": 1.0,
    }


def _spoken_text(text: str, mood: str) -> str:
    """Remove pause-heavy punctuation while retaining natural sentence cues."""
    spoken = " ".join(str(text).replace("…", ".").replace("...", ".").split())
    spoken = spoken.replace(";", ",").replace(" — ", ", ").replace(" – ", ", ")
    if mood in {"tense", "dramatic"} and spoken.endswith("?"):
        return spoken
    return spoken


def _script_narration_sources(script) -> list[dict]:
    if script is None:
        return []
    blocks = [getattr(script, "hook", "")]
    blocks.extend(getattr(section, "narration", "") for section in getattr(script, "sections", []))
    blocks.extend([getattr(script, "conclusion", ""), getattr(script, "call_to_action", "")])
    sentences = []
    for block in blocks:
        sentences.extend(
            part.strip() for part in __import__("re").split(r"(?<=[.!?])\s+", str(block).strip())
            if part.strip()
        )
    return [
        {
            "scene_id": index, "narration": sentence,
            "voice_emotion": "serious", "music_mood": "restrained_tension",
            "visual_type": "ai_reconstruction",
        }
        for index, sentence in enumerate(sentences, 1)
    ]


def _concat_narration(output_dir: Path, paths: list[Path]) -> Path | None:
    if not paths:
        return None
    audio_dir = output_dir / "audio"
    manifest = audio_dir / "narration_concat.txt"
    manifest.write_text(
        "".join(f"file '{path.resolve().as_posix()}'\n" for path in paths), encoding="utf-8",
    )
    output = output_dir / "narration.wav"
    result = subprocess.run(
        [settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c:a", "pcm_s16le", str(output)],
        capture_output=True, text=True,
    )
    if result.returncode:
        logger.warning("narration_concat_failed", error=result.stderr[-500:])
        return None
    return output
