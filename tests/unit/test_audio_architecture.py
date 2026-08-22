import json

import pytest


def _bank_scene():
    return json.loads(open("config/audio_bank_test_scene.json", encoding="utf-8").read())


def test_speech_markup_preserves_emotion_and_pause():
    from app.audio.speech_markup import parse_speech_markup, plain_speech_text

    markup = "<emotion=serious>The city changed.</emotion><pause=0.5><speed=0.9>Everything changed.</speed>"
    segments = parse_speech_markup(markup)
    assert segments[0].controls["emotion"] == "serious"
    assert any(segment.pause_seconds == .5 for segment in segments)
    assert plain_speech_text(markup) == "The city changed. .  Everything changed."


def test_piper_reports_missing_model_without_fallback(monkeypatch):
    from app.audio.models import VoicePack
    from app.audio.voice_provider import PiperLocalVoiceProvider, VoiceProviderUnavailable

    monkeypatch.delenv("PIPER_MODEL_PATH", raising=False)
    provider = PiperLocalVoiceProvider(model_path=None)
    voice = VoicePack("test", "Test", "neutral", "adult", "Indian", "en-IN", "calm")
    assert provider.available is False
    assert "model" in provider.unavailable_reason.lower()
    with pytest.raises(VoiceProviderUnavailable, match="(?i)model"):
        provider.generate_speech("Hello", voice, __import__("pathlib").Path("unused.wav"))


def test_piper_rejects_fake_whisper_instead_of_ignoring_it(monkeypatch, tmp_path):
    from app.audio.models import VoicePack
    from app.audio.voice_provider import PiperLocalVoiceProvider, VoiceProviderUnavailable

    model = tmp_path / "voice.onnx"; model.write_bytes(b"model")
    monkeypatch.setattr("shutil.which", lambda _: "piper.exe")
    provider = PiperLocalVoiceProvider(model)
    voice = VoicePack("test", "Test", "neutral", "adult", "Indian", "en-IN", "calm")
    with pytest.raises(VoiceProviderUnavailable, match="whisper"):
        provider.generate_speech("<whisper=true>Secret</whisper>", voice, tmp_path / "out.wav")


def test_audio_director_builds_synchronized_bank_plan(tmp_path):
    from app.audio.director import AudioDirector

    data = _bank_scene()
    plan = AudioDirector().plan(data["scenes"], tmp_path, data["language"], data["characters"])
    assert plan["duration"] == 30
    assert plan["production_ready"] is False
    assert {event["type"] for event in plan["events"]} >= {"voice", "foley", "sfx", "ambience", "music", "silence"}
    assert {event["source"] for event in plan["events"]} >= {
        "library://footsteps_indoor_leather", "library://wooden_bank_door_open_close",
        "library://bank_room_tone_1980s", "library://ceiling_fan_period",
        "library://distant_bank_people_1980s", "library://wooden_chair_creak_impact",
        "library://cotton_clothing_movement",
    }
    voices = [event for event in plan["events"] if event["type"] == "voice"]
    assert {event["source"] for event in voices} == {"voicepack://narrator_en_01"}
    assert all({"audio_id", "type", "start", "duration", "source", "volume_db", "pan", "fade_in", "fade_out", "priority", "scene", "shot", "character", "emotion", "layer"} <= set(event) for event in plan["events"])
    assert max(event["duration"] for event in plan["events"] if event["type"] == "music") < 30
    assert not any("phone" in event["source"] or "modern" in event["source"] for event in plan["events"])
    assert (tmp_path / "audio" / "audio_plan.json").is_file()
    assert (tmp_path / "audio" / "reports" / "dependency_report.json").is_file()
    assert (tmp_path / "audio" / "versions" / "audio_v001" / "audio_plan.json").is_file()


def test_audio_plan_versions_preserve_previous_plan(tmp_path):
    from app.audio.director import AudioDirector

    data = _bank_scene(); director = AudioDirector()
    first = director.plan(data["scenes"], tmp_path, data["language"], data["characters"])
    second = director.plan(data["scenes"], tmp_path, data["language"], data["characters"])
    assert first["audio_version"] == "audio_v001"
    assert second["audio_version"] == "audio_v002"
    assert (tmp_path / "audio" / "versions" / "audio_v001" / "audio_plan.json").is_file()
    assert (tmp_path / "audio" / "versions" / "audio_v002" / "audio_plan.json").is_file()
