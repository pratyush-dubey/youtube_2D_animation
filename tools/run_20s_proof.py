"""Build the isolated 20-second action proof; never starts a long production."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

from app.audio.voice_provider import PiperLocalVoiceProvider
from app.audio.voicepacks import VoicePackRegistry
from app.config.settings import settings
from app.images.production_assets import extract_character_rig, extract_environment_layers, remove_subject_background
from app.metadata.sanitizer import sanitize_metadata_payload
from app.qa.identity import inspect_identity
from app.qa.media import inspect_render
from app.timeline.master import build_master_timeline, measure_audio_duration
from app.thumbnail.generator import render_thumbnail
from app.video.animated_renderer import Cinematic2DRenderer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "proofs" / "muthappa_rai_20s"
CHARACTER = ROOT / "character_library" / "muthappa_rai" / "full_body_v3.png"
REFERENCE = ROOT / "character_library" / "muthappa_rai" / "reference" / "india_today_2020.jpg"
ENVIRONMENT = OUT / "assets" / "bengaluru_street.png"
LINES = (
    "In the late nineteen eighties, Bengaluru's streets carried a tense new rhythm.",
    "Muthappa Rai walks toward a bank entrance, moving with deliberate confidence.",
    "At the curb, he stops as traffic passes behind him.",
    "He looks around, checking both ends of the crowded street.",
    "Then he opens the bank door and enters, while the city continues outside.",
)


def _run(*args: str) -> None:
    subprocess.run(list(args), check=True, capture_output=True, text=True)


def narration() -> tuple[list[dict], Path]:
    narration_dir = OUT / "audio" / "narration"
    narration_dir.mkdir(parents=True, exist_ok=True)
    voice = VoicePackRegistry().narrator("English")
    provider = PiperLocalVoiceProvider(ROOT / "assets/voices/en_US-lessac-medium.onnx", settings.piper_executable)
    raw_paths = []
    for index, line in enumerate(LINES, 1):
        path = narration_dir / f"raw_{index:03d}.wav"
        provider.generate_speech(f"<emotion=serious>{line}</emotion>", voice, path)
        raw_paths.append(path)
    raw_total = sum(measure_audio_duration(path) for path in raw_paths)
    tempo = raw_total / 20.0
    if not 0.5 <= tempo <= 2.0:
        raise RuntimeError(f"Narration cannot be safely conformed to 20 seconds (atempo={tempo:.3f})")
    target_lengths = [measure_audio_duration(path) / tempo for path in raw_paths]
    target_lengths[-1] = 20.0 - sum(target_lengths[:-1])
    sources = []
    conformed = []
    for index, (line, raw, target) in enumerate(zip(LINES, raw_paths, target_lengths), 1):
        path = narration_dir / f"segment_{index:03d}.wav"
        _run(settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw),
             "-af", f"atempo={tempo:.6f},apad,atrim=duration={target:.6f}", "-c:a", "pcm_s16le", str(path))
        sources.append({
            "shot_id": f"S{index:03d}", "text": line, "audio_path": str(path),
            "character_id": None if index == 1 else "muthappa_rai",
            "environment": "1980s Bengaluru bank street with moving traffic, pedestrians, and a shop fan",
            "emotion": "serious", "visual_type": "ai_reconstruction",
        })
        conformed.append(AudioSegment.from_wav(path))
    combined = sum(conformed, AudioSegment.silent(duration=0))[:20000]
    narration_path = OUT / "audio" / "narration.wav"
    combined.export(narration_path, format="wav", parameters=["-acodec", "pcm_s16le"])
    return sources, narration_path


def designed_sound(timeline: dict) -> tuple[Path, Path, list[dict]]:
    audio_dir = OUT / "audio"
    ambience = WhiteNoise().to_audio_segment(duration=20000).low_pass_filter(1100) - 43
    city_hum = Sine(92).to_audio_segment(duration=20000).fade_in(1200).fade_out(1200) - 38
    sfx = ambience.overlay(city_hum)
    rendered_cues = []
    for event in timeline["tracks"]["sfx"]:
        if event["source"] == "footsteps":
            start_ms, end_ms = round(event["start"] * 1000), round(event["end"] * 1000)
            for at in range(start_ms, end_ms, 440):
                step = Sine(145).to_audio_segment(duration=95).fade_out(80) - 21
                sfx = sfx.overlay(step, position=at)
            rendered_cues.append({"event_id": event["event_id"], "source": "footsteps", "start": event["start"], "end": event["end"]})
        elif event["source"] == "door":
            door = Sine(210).to_audio_segment(duration=680).fade_in(120).fade_out(430) - 20
            sfx = sfx.overlay(door, position=round(event["start"] * 1000))
            rendered_cues.append({"event_id": event["event_id"], "source": "door", "start": event["start"], "end": event["end"]})
    sfx_path = audio_dir / "sfx.wav"
    sfx.export(sfx_path, format="wav", parameters=["-acodec", "pcm_s16le"])
    music = AudioSegment.silent(duration=20000)
    for frequency in (55, 82, 110):
        music = music.overlay(Sine(frequency).to_audio_segment(duration=20000).fade_in(1800).fade_out(1600) - 44)
    music_path = audio_dir / "music.wav"
    music.export(music_path, format="wav", parameters=["-acodec", "pcm_s16le"])
    combined_path = audio_dir / "designed_sound.wav"
    sfx.overlay(music).export(combined_path, format="wav", parameters=["-acodec", "pcm_s16le"])
    (audio_dir / "audio_cues.json").write_text(json.dumps(rendered_cues, indent=2), encoding="utf-8")
    return combined_path, music_path, rendered_cues


def write_subtitles(timeline: dict) -> Path:
    def stamp(seconds: float) -> str:
        millis = round(seconds * 1000)
        hours, millis = divmod(millis, 3_600_000)
        minutes, millis = divmod(millis, 60_000)
        secs, millis = divmod(millis, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    blocks = []
    for cue in timeline["tracks"]["subtitles"]:
        blocks.append(f"{cue['cue_id']}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{cue['text']}")
    path = OUT / "subtitles.srt"
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def main() -> int:
    if not CHARACTER.is_file() or not ENVIRONMENT.is_file():
        missing = [str(path) for path in (CHARACTER, ENVIRONMENT) if not path.is_file()]
        raise FileNotFoundError("Proof assets are missing: " + ", ".join(missing))
    OUT.mkdir(parents=True, exist_ok=True)
    sources, narration_path = narration()
    timeline = build_master_timeline(
        sources, environment="1980s Bengaluru bank street", output_path=OUT / "timeline.json"
    )
    # Conformance is frame-accurate at 30fps; reject accidental drift early.
    if abs(float(timeline["duration"]) - 20.0) > 0.034:
        raise RuntimeError(f"Proof clock is {timeline['duration']} seconds, not 20 seconds")
    cutout = remove_subject_background(CHARACTER, OUT / "assets/character_cutout.png")
    identity = inspect_identity(REFERENCE, CHARACTER, OUT / "identity_report.json")
    if not identity["passed"]:
        raise RuntimeError("Identity continuity failed; proof render stopped")
    rig = extract_character_rig(cutout, OUT / "assets/rig")
    layers = extract_environment_layers(ENVIRONMENT, OUT / "assets/environment_layers")
    framing = {"wide": "wide", "medium": "medium", "closeup": "closeup", "over_shoulder": "over_shoulder"}
    camera = {"tracking": "track_character", "follow": "follow_character", "settle": "slow_push", "subtle_orbit": "orbit_simulation", "dolly": "slow_push"}
    shots = []
    for shot in timeline["shots"]:
        shots.append({
            **shot, "shot_type": framing.get(shot["framing"], "medium"),
            "camera": {"move": camera.get(shot["camera"]["move"], "slow_push"), "start": {"zoom": 1.01}, "end": {"zoom": 1.06}},
            "expression": "serious",
        })
    scene = {
        "scene_id": 1, "duration_seconds": timeline["duration"], "shots": shots,
        "character_name": "Muthappa Rai", "character_rig_manifest": str(rig),
        "environment_assets": {name: str(path) for name, path in layers.items()},
        "interactive_regions": {"door": [0.58, 0.36, 0.67, 0.80]},
        "visual_description": "1980s Bengaluru street outside a bank",
        "visual_quality": "PRODUCTION", "seed": 19851203,
    }
    (OUT / "scene.json").write_text(json.dumps(scene, indent=2), encoding="utf-8")
    designed_sound_path, _music_path, audio_cues = designed_sound(timeline)
    subtitle_path = write_subtitles(timeline)
    video = Cinematic2DRenderer(1280, 720, 30).render_scene(
        scene, ENVIRONMENT, OUT / "proof_20s.mp4", narration_path, designed_sound_path, quality="DRAFT"
    )
    metadata = sanitize_metadata_payload({
        "best_title": "Muthappa Rai: A Bengaluru Story", "description": "A short documentary reconstruction.",
        "tags": ["Muthappa Rai", "Bengaluru", "documentary"], "hashtags": ["#Documentary"],
    })
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    thumbnail_candidates = [
        {"id": 1, "main_text": "MUTHAPPA RAI", "sub_text": "BENGALURU STORY", "background_color": "#07141a", "background_color_2": "#1a2d31", "text_color": "#ffffff", "accent_color": "#d99a43"},
        {"id": 2, "main_text": "THE RAI YEARS", "sub_text": "1980s BENGALURU", "background_color": "#101820", "background_color_2": "#27343a", "text_color": "#ffffff", "accent_color": "#d99a43"},
        {"id": 3, "main_text": "BENGALURU FILES", "sub_text": "MUTHAPPA RAI", "background_color": "#151515", "background_color_2": "#303030", "text_color": "#ffffff", "accent_color": "#c98b3a"},
    ]
    for candidate in thumbnail_candidates:
        words = len(candidate["main_text"].split())
        candidate["score"] = (30 if "RAI" in candidate["main_text"] else 18) + (25 if words <= 3 else 15) + (25 if "MUTHAPPA" in (candidate["main_text"] + candidate["sub_text"]) else 15) + 20
        candidate["background_image"] = str(ENVIRONMENT)
        candidate["focal_image"] = str(cutout)
    selected = max(thumbnail_candidates, key=lambda item: item["score"])
    (OUT / "thumbnail_candidates.json").write_text(json.dumps({"selected_id": selected["id"], "candidates": thumbnail_candidates}, indent=2), encoding="utf-8")
    render_thumbnail(selected, OUT / "thumbnail.jpg")
    report = inspect_render(video, timeline, metadata=metadata, audio_cues=audio_cues, subtitle_path=subtitle_path, output_path=OUT / "qa_report.json")
    shutil.copy2(OUT / "qa_report.json", OUT / "quality_report.json")
    _run(settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-c:a", "pcm_s16le", str(OUT / "audio/master_audio.wav"))
    (OUT / "shot_manifest.json").write_text(json.dumps({"schema_version": "2.0", "shots": timeline["shots"]}, indent=2), encoding="utf-8")
    shutil.copy2(video, OUT / "final.mp4")
    shutil.copy2(OUT / "metadata.json", OUT / "seo.json")
    for name in ("narration.wav", "sfx.wav", "music.wav", "master_audio.wav"):
        shutil.copy2(OUT / "audio" / name, OUT / name)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
