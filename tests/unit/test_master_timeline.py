from __future__ import annotations

import wave


def _silence(path, duration: float) -> None:
    frames = round(16000 * duration)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * frames)


def test_master_timeline_uses_measured_audio_and_one_clock(tmp_path):
    from app.timeline.master import build_master_timeline

    first, second = tmp_path / "one.wav", tmp_path / "two.wav"
    _silence(first, 2.25); _silence(second, 3.5)
    timeline = build_master_timeline([
        {"text": "Muthappa walks along the street.", "audio_path": first},
        {"text": "He stops and looks left.", "audio_path": second},
    ], character_id="muthappa_rai", environment="1980s Bengaluru street")

    assert timeline["duration"] == 5.75
    assert [shot["start"] for shot in timeline["shots"]] == [0.0, 2.25]
    assert [shot["end"] for shot in timeline["shots"]] == [2.25, 5.75]
    assert timeline["tracks"]["subtitles"] == [
        {"cue_id": 1, "start": 0.0, "end": 2.25, "text": "Muthappa walks along the street.", "source_event_id": "N001"},
        {"cue_id": 2, "start": 2.25, "end": 5.75, "text": "He stops and looks left.", "source_event_id": "N002"},
    ]
    assert timeline["shots"][0]["action"] == "walk"
    assert timeline["shots"][1]["actions"] == ["stop", "look_left"]
    assert timeline["shots"][0]["animation_plan"]["character"]["camera_motion_excluded_from_score"] is True


def test_metadata_sanitizer_removes_html_from_every_public_field():
    from app.metadata.sanitizer import sanitize_metadata_payload

    clean = sanitize_metadata_payload({
        "best_title": "<B>The Truth</B>",
        "description": "A &amp; B <script>alert(1)</script>",
        "tags": ["<i>tag</i>"],
        "chapters": [{"time": "0:00", "label": "<b>Intro</b>"}],
        "title_candidates": [{"title": "<strong>Story</strong>", "reason": "<em>clear</em>"}],
    })
    assert clean["best_title"] == "The Truth"
    assert "<" not in str(clean)


def test_timeline_sfx_never_runs_past_its_shot(tmp_path):
    from app.timeline.master import build_master_timeline

    first, second = tmp_path / "first.wav", tmp_path / "second.wav"
    _silence(first, 0.7); _silence(second, 0.7)
    timeline = build_master_timeline([
        {"text": "He walks on the street.", "audio_path": first, "character_id": "actor", "environment": "street"},
        {"text": "He opens the door.", "audio_path": second, "character_id": "actor", "environment": "street"},
    ])
    shots = {shot["shot_id"]: shot for shot in timeline["shots"]}
    assert all(event["end"] <= shots[event["shot_id"]]["end"] for event in timeline["tracks"]["sfx"])
