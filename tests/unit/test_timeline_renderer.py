from __future__ import annotations


def test_scene_is_expanded_into_shots_layers_and_tracks():
    from app.video.timeline import build_production_scene

    scene = build_production_scene({
        "scene_id": 4,
        "duration_seconds": 8,
        "narration": "Ravi entered the abandoned house and slowly opened the door.",
        "visual_description": "dark hallway with fog",
        "character_name": "Ravi",
        "character_motion": "walk-in-left",
        "music_mood": "tense",
    })

    assert len(scene["shots"]) == 4
    assert {shot["shot_type"] for shot in scene["shots"]} >= {"wide", "medium", "closeup"}
    assert sum(shot["duration"] for shot in scene["shots"]) == 8
    assert {layer["type"] for layer in scene["layers"]} >= {"environment", "character", "fx", "lighting"}
    assert {track["name"] for track in scene["timeline"]["tracks"]} >= {
        "camera", "environment", "character", "atmosphere", "lighting", "audio",
    }
    assert scene["animation_quality"]["passed"] is True


def test_same_scene_produces_deterministic_plan():
    from app.video.timeline import build_production_scene

    source = {
        "scene_id": 1,
        "duration_seconds": 5,
        "narration": "A woman turns toward the sound.",
        "character_name": "Maya",
    }
    first = build_production_scene(source)
    second = build_production_scene(source)
    assert first == second


def test_static_llm_plan_is_repaired_before_rendering():
    from app.video.timeline import build_production_scene

    scene = build_production_scene({
        "scene_id": 2,
        "duration_seconds": 4,
        "narration": "The room becomes quiet.",
        "shots": [{"duration": 4, "shot_type": "wide", "camera": "static", "action": "idle"}],
    })
    assert scene["animation_quality"]["score"] >= 70
    assert all(shot["camera"]["move"] != "static" for shot in scene["shots"])


def test_custom_forest_timing_is_preserved():
    from app.video.timeline import build_production_scene

    durations = [2, 3, 2, 2, 1]
    scene = build_production_scene({
        "scene_id": 1,
        "duration_seconds": 10,
        "character_name": "Ravi",
        "shots": [
            {"duration": duration, "shot_type": shot_type, "camera": camera, "action": action}
            for duration, shot_type, camera, action in zip(
                durations,
                ["wide", "medium", "medium", "closeup", "rear"],
                ["slow_push", "track_character", "dolly_in", "handheld", "orbit_simulation"],
                ["walk", "walk", "turn_head", "react", "stop"],
            )
        ],
    })
    assert [shot["duration"] for shot in scene["shots"]] == durations
    assert [shot["start"] for shot in scene["shots"]] == [0, 2, 5, 7, 9]

