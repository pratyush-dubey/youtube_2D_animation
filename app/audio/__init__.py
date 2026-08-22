"""
Audio processing module.

Provides AudioMixer — a thin abstraction over pydub + FFmpeg for
mixing narration, music, and SFX tracks.

Usage:
    from app.audio.mixer import AudioMixer
    mixer = AudioMixer()
    mixer.mix(narration_files, music_path, sfx_list, output_path)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.audio.models import AudioEvent, VoicePack
from app.audio.voice_provider import VoiceProvider

__all__ = ["AudioMixer", "AudioEvent", "VoicePack", "VoiceProvider"]


class AudioMixer:
    """
    Mix narration, background music, and SFX into a single audio track.

    All level adjustments follow the dB settings in config:
      NARRATION_VOLUME_DB  (default -3 dB)
      MUSIC_DUCK_DB        (default -18 dB while narration plays)
      SFX_VOLUME_DB        (default -14 dB)
    """

    def mix_narration_files(
        self,
        narration_files: dict[int, Path],
        scene_durations: list[float],
        output_path: Path,
        padding_seconds: float = 0.5,
    ) -> Path:
        """
        Concatenate per-scene narration files with silence padding between scenes.
        Returns the path to the combined narration WAV/MP3.
        """
        try:
            from pydub import AudioSegment
        except ImportError:
            raise ImportError("pydub is required: pip install pydub")

        from app.config.settings import settings
        combined = AudioSegment.silent(duration=0)
        silence = AudioSegment.silent(duration=int(padding_seconds * 1000))

        for scene_id in sorted(narration_files):
            path = narration_files[scene_id]
            if path.exists() and path.stat().st_size > 100:
                seg = AudioSegment.from_file(str(path))
                seg = seg + settings.narration_volume_db  # apply gain
                combined += seg + silence
            else:
                # Pad with silence matching scene duration
                idx = scene_id - 1
                dur_ms = int(scene_durations[idx] * 1000) if idx < len(scene_durations) else 4000
                combined += AudioSegment.silent(duration=dur_ms)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.export(str(output_path), format="mp3")
        return output_path

    def duck_music(
        self,
        music_path: Path,
        narration_duration_ms: int,
        output_path: Path,
    ) -> Path:
        """
        Create a ducked music track: lower volume while narration plays,
        fade up at the end. Uses pydub for manipulation.
        """
        from pydub import AudioSegment
        from app.config.settings import settings

        music = AudioSegment.from_file(str(music_path))

        # Loop music to cover the full duration
        if len(music) < narration_duration_ms + 10_000:
            loops_needed = (narration_duration_ms + 10_000) // len(music) + 1
            music = music * loops_needed

        music = music[:narration_duration_ms + 5_000]
        ducked = music + settings.music_duck_db  # apply duck gain

        # Fade out at the end
        ducked = ducked.fade_out(3000)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        ducked.export(str(output_path), format="mp3")
        return output_path
