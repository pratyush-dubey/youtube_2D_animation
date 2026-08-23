"""Independent voice-provider contracts with an honest local Piper adapter."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from app.audio.models import VoicePack
from app.audio.speech_markup import parse_speech_markup, plain_speech_text


class VoiceProviderUnavailable(RuntimeError):
    pass


class VoiceProvider(ABC):
    provider_id = "abstract"

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @property
    @abstractmethod
    def unavailable_reason(self) -> str | None: ...

    @abstractmethod
    def generate_speech(self, markup: str, voice: VoicePack, output: Path, pronunciation: dict | None = None) -> Path: ...

    @abstractmethod
    def list_voices(self) -> list[str]: ...

    @abstractmethod
    def get_voice_metadata(self, voice_id: str) -> dict: ...

    @abstractmethod
    def preview_voice(self, voice: VoicePack, output: Path) -> Path: ...

    @abstractmethod
    def estimate_duration(self, markup: str, voice: VoicePack) -> float: ...


class PiperLocalVoiceProvider(VoiceProvider):
    provider_id = "piper_local"

    def __init__(self, model_path: Path | None = None, executable: str = "piper"):
        configured = str(model_path or os.getenv("PIPER_MODEL_PATH", "")).strip()
        self.model_path = Path(configured).expanduser() if configured else None
        self.executable = executable

    @property
    def available(self) -> bool:
        return bool(shutil.which(self.executable) and self.model_path and self.model_path.is_file())

    @property
    def unavailable_reason(self) -> str | None:
        if not shutil.which(self.executable):
            return "Piper executable is not installed or not on PATH"
        if not self.model_path:
            return "Piper is installed, but PIPER_MODEL_PATH is not configured"
        if not self.model_path.is_file():
            return f"Piper voice model does not exist: {self.model_path}"
        return None

    def generate_speech(self, markup: str, voice: VoicePack, output: Path, pronunciation: dict | None = None) -> Path:
        if not self.available:
            raise VoiceProviderUnavailable(self.unavailable_reason or "Piper is unavailable")
        segments = parse_speech_markup(markup)
        output = output.with_suffix(".wav")
        output.parent.mkdir(parents=True, exist_ok=True)
        if any(segment.controls.get("whisper") for segment in segments):
            raise VoiceProviderUnavailable("The selected Piper voice does not support true whisper synthesis")
        try:
            from pydub import AudioSegment
        except ImportError as exc:
            raise VoiceProviderUnavailable("pydub is required for marked-up Piper speech") from exc

        combined = AudioSegment.silent(duration=0)
        with tempfile.TemporaryDirectory(prefix="piper_segments_") as temporary:
            temp = Path(temporary)
            for index, segment in enumerate(segments):
                if segment.pause_seconds:
                    combined += AudioSegment.silent(duration=round(segment.pause_seconds * 1000))
                    continue
                if not segment.text:
                    continue
                controls = segment.controls
                emotion = str(controls.get("emotion", "calm"))
                emotion_profile = voice.emotion_profile.get(emotion, {})
                speed = float(controls.get("speed", 1.0)) * float(emotion_profile.get("speed", 1.0))
                if controls.get("emphasis"):
                    speed *= .97
                rate = max(.5, min(voice.speaking_rate * speed, 1.8))
                volume_db = float(controls.get("volume", 0.0)) + (1.5 if controls.get("emphasis") else 0.0)
                volume_multiplier = max(.1, min(10 ** (volume_db / 20), 3.0))
                raw = temp / f"segment_{index:03d}_raw.wav"
                command = [
                    self.executable, "--model", str(self.model_path), "--output_file", str(raw),
                    "--length-scale", f"{1.0 / rate:.3f}", "--sentence-silence", "0.12",
                    "--volume", f"{volume_multiplier:.3f}",
                ]
                text = plain_speech_text(segment.text, pronunciation)
                result = subprocess.run(command, input=text, text=True, capture_output=True)
                if result.returncode or not raw.is_file() or raw.stat().st_size < 1000:
                    raise RuntimeError((result.stderr or "Piper produced no usable WAV")[-1000:])
                pitch = float(controls.get("pitch", 0.0)) + float(emotion_profile.get("pitch", 0.0)) + voice.pitch
                rendered = self._pitch_shift(raw, temp / f"segment_{index:03d}.wav", pitch) if abs(pitch) >= .1 else raw
                combined += AudioSegment.from_wav(str(rendered))
        if len(combined) == 0:
            raise RuntimeError("Speech markup contained no renderable text")
        combined.export(str(output), format="wav", parameters=["-acodec", "pcm_s16le"])
        if not output.is_file() or output.stat().st_size < 1000:
            raise RuntimeError("Piper produced no usable final WAV")
        return output

    @staticmethod
    def _pitch_shift(source: Path, output: Path, semitones: float) -> Path:
        """Pitch-shift while approximately preserving duration using FFmpeg."""
        import wave
        from app.config.settings import settings
        factor = 2 ** (max(-8.0, min(semitones, 8.0)) / 12)
        with wave.open(str(source), "rb") as audio:
            sample_rate = audio.getframerate()
        adjusted_rate = round(sample_rate * factor)
        filters = f"asetrate={adjusted_rate},aresample={sample_rate},atempo={1 / factor:.6f}"
        result = subprocess.run(
            [settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-af", filters, "-c:a", "pcm_s16le", str(output)],
            capture_output=True, text=True,
        )
        if result.returncode or not output.is_file():
            raise RuntimeError((result.stderr or "FFmpeg pitch processing failed")[-1000:])
        return output

    def list_voices(self) -> list[str]:
        return [self.model_path.stem] if self.model_path and self.model_path.is_file() else []

    def get_voice_metadata(self, voice_id: str) -> dict:
        config = Path(f"{self.model_path}.json") if self.model_path else None
        if config and config.is_file():
            return json.loads(config.read_text(encoding="utf-8"))
        return {"voice_id": voice_id, "provider": self.provider_id, "model_path": str(self.model_path or "")}

    def preview_voice(self, voice: VoicePack, output: Path) -> Path:
        return self.generate_speech("<emotion=calm>This is the documentary narrator voice.</emotion>", voice, output)

    def estimate_duration(self, markup: str, voice: VoicePack) -> float:
        words = len(plain_speech_text(markup).split())
        return round(max(0.5, words / (150 * max(voice.speaking_rate, .5)) * 60), 3)


class ImportedVoiceProvider(VoiceProvider):
    """Catalogues licensed recordings; it never pretends to synthesize new text."""
    provider_id = "imported_voice"

    def __init__(self, root: Path):
        self.root = root

    @property
    def available(self) -> bool:
        return self.root.is_dir() and any(self.root.rglob("*.wav"))

    @property
    def unavailable_reason(self) -> str | None:
        return None if self.available else "No imported, licensed WAV recordings are available"

    def generate_speech(self, markup: str, voice: VoicePack, output: Path, pronunciation: dict | None = None) -> Path:
        raise VoiceProviderUnavailable("ImportedVoiceProvider cannot synthesize arbitrary text")

    def list_voices(self) -> list[str]:
        return sorted(path.stem for path in self.root.rglob("*.wav")) if self.root.is_dir() else []

    def get_voice_metadata(self, voice_id: str) -> dict:
        return {"voice_id": voice_id, "provider": self.provider_id, "rights_required": True}

    def preview_voice(self, voice: VoicePack, output: Path) -> Path:
        raise VoiceProviderUnavailable("Select a specific licensed imported sample for preview")

    def estimate_duration(self, markup: str, voice: VoicePack) -> float:
        return round(max(.5, len(plain_speech_text(markup).split()) / 150 * 60), 3)


def create_local_voice_provider(voice: VoicePack | None = None) -> VoiceProvider:
    from app.config.settings import settings
    model = (
        (voice.provider_config.get("model_path") if voice else None)
        or os.getenv("PIPER_MODEL_PATH")
        or getattr(settings, "piper_model_path", "")
    )
    executable = os.getenv("PIPER_EXECUTABLE") or settings.piper_executable
    return PiperLocalVoiceProvider(Path(model) if model else None, executable)
