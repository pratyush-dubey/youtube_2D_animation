from __future__ import annotations


def test_long_storyboard_scene_becomes_short_visual_beats():
    from app.agents.storyboard_agent import _prepare_scenes

    narration = (
        "Heavy rocks move across the desert floor without human intervention. "
        "Thin ice forms overnight, and a gentle wind pushes the rocks slowly forward."
    )
    scenes = _prepare_scenes([
        {
            "scene_id": 1,
            "duration_seconds": 24,
            "narration": narration,
            "visual_description": "Sailing stones in Death Valley",
            "image_prompt": "Accurate sailing stones on cracked mud",
            "text_overlay": "Sailing Stones",
        }
    ])

    assert len(scenes) >= 2
    assert max(scene["duration_seconds"] for scene in scenes) <= 8
    assert max(len(scene["narration"].split()) for scene in scenes) <= 22
    assert " ".join(scene["narration"] for scene in scenes) == narration
    assert scenes[0]["text_overlay"] == "Sailing Stones"
    assert all(scene["text_overlay"] is None for scene in scenes[1:])


def test_missing_script_section_is_recovered_before_conclusion():
    from app.agents.storyboard_agent import _ensure_script_sections
    from app.script.schemas import ScriptResult

    script = ScriptResult.model_validate({
        "title": "Two Mysteries",
        "hook": "A hook.",
        "sections": [
            {"id": 1, "title": "First", "narration": "The first mystery is explained.", "duration_seconds": 10},
            {"id": 2, "title": "Second", "narration": "The missing second mystery belongs here.", "duration_seconds": 10},
        ],
        "conclusion": "Both mysteries change what we know.",
    })
    scenes = [
        {"scene_id": 1, "narration": "The first mystery is explained."},
        {"scene_id": 2, "narration": "Both mysteries change what we know."},
    ]

    result = _ensure_script_sections(scenes, script, "Mysteries")

    assert any("missing second mystery" in scene["narration"] for scene in result)
    assert "Both mysteries" in result[-1]["narration"]
    assert [scene["scene_id"] for scene in result] == list(range(1, len(result) + 1))


def test_caption_chunks_are_short_and_lossless():
    from app.agents.video_edit_agent import _caption_chunks

    text = "These captions remain readable because each phrase contains only a few carefully grouped spoken words."
    chunks = _caption_chunks(text)

    assert max(len(chunk.split()) for chunk in chunks) <= 7
    assert " ".join(chunks) == text


def test_numbered_title_is_aligned_to_section_count():
    from app.script.schemas import ScriptResult
    from app.script.script_generator import _align_numbered_title

    script = ScriptResult.model_validate({
        "title": "10 Places Science Cannot Explain",
        "hook": "Hook",
        "sections": [
            {"id": i, "title": str(i), "narration": "Narration", "duration_seconds": 5}
            for i in range(1, 7)
        ],
    })

    assert _align_numbered_title(script).title == "6 Places Science Cannot Explain"


def test_prompt_relevance_detects_unrelated_visual():
    from app.agents.quality_agent import _weak_visual_prompts

    scenes = [{
        "scene_id": 4,
        "narration": "Gobekli Tepe has distinctive T-shaped stone pillars.",
        "visual_description": "Accurate archaeological reconstruction in Turkey",
        "image_prompt": "A generic futuristic sports car in a neon city",
    }]

    assert _weak_visual_prompts(scenes) == [4]


def test_structured_documentary_assets_have_distinct_compositions(tmp_path):
    from PIL import Image, ImageChops, ImageStat

    from app.images.editorial_compositor import enhance_structured_asset

    outputs = []
    for scene_id, asset_type in enumerate(
        ("animated-map", "newspaper-document", "evidence-board"), start=1
    ):
        path = tmp_path / f"{asset_type}.jpg"
        Image.new("RGB", (640, 360), "#123126").save(path)
        enhance_structured_asset(path, asset_type, scene_id)
        image = Image.open(path).convert("RGB")
        assert image.size == (1920, 1080)
        outputs.append(image.resize((64, 36)))

    for left, right in zip(outputs, outputs[1:]):
        difference = ImageStat.Stat(ImageChops.difference(left, right)).mean
        assert sum(difference) > 10


def test_cinematic_overlay_styles_follow_asset_type():
    from app.agents.video_edit_agent import _ass_overlay_style

    assert _ass_overlay_style({"asset_type": "date-card"}) == "Date"
    assert _ass_overlay_style({"asset_type": "animated-map"}) == "Location"
    assert _ass_overlay_style({"asset_type": "evidence-board"}) == "Evidence"


def test_character_sprite_is_consistent_and_motion_is_animated(tmp_path):
    from PIL import Image

    from app.video.character_motion import (
        character_overlay_expression,
        create_character_sprite,
    )

    first = create_character_sprite(tmp_path, "Maya Rao", "forest-green field coat")
    second = create_character_sprite(tmp_path, "Maya Rao", "forest-green field coat")
    assert first == second
    assert Image.open(first).mode == "RGBA"

    x_expr, y_expr = character_overlay_expression("walk-in-right", "right", 5.0)
    assert "t*" in x_expr
    assert "sin" in y_expr


def test_storyboard_normalises_character_motion_fields():
    from app.agents.storyboard_agent import _normalise_scene

    scene = _normalise_scene(
        {
            "character_name": "Maya Rao",
            "character_motion": "walk_in_left",
            "character_position": "invalid",
            "character_scale": 5,
        },
        1,
    )
    assert scene["character_motion"] == "walk-in-left"
    assert scene["character_position"] == "right"
    assert scene["character_scale"] == 1.0
    assert scene["character_is_fictional"] is False


def test_character_agent_never_invents_people_when_research_has_none():
    from app.agents.character_agent import _fallback_character_sheet, _person_names

    assert _fallback_character_sheet("An unexplained place", [])["characters"] == []
    assert _person_names([{"name": "A. P. J. Abdul Kalam"}]) == [
        "A. P. J. Abdul Kalam"
    ]


def test_real_character_sprite_requires_verified_reference(tmp_path):
    from PIL import Image

    from app.video.character_motion import character_reference, create_character_sprite

    reference = tmp_path / "portrait.jpg"
    Image.new("RGB", (600, 800), "#777777").save(reference)
    sheet = {
        "characters": [{
            "name": "Named Person",
            "reference_image": str(reference),
            "identity_reference_status": "verified-user-reference",
        }]
    }
    assert character_reference(sheet, "Named Person") == reference
    sprite = create_character_sprite(
        tmp_path, "Named Person", reference_path=reference
    )
    assert Image.open(sprite).mode == "RGBA"

    unsafe = {"characters": [{"name": "Named Person"}]}
    assert character_reference(unsafe, "Named Person") is None


def test_voice_delivery_changes_with_story_emotion():
    from app.agents.voice_agent import _delivery_profile, _spoken_text

    calm = _delivery_profile({"music_mood": "calm"}, 3, 8, 1.10)
    tense_hook = _delivery_profile(
        {"voice_emotion": "tense", "motion_intensity": "high"}, 0, 8, 1.10
    )
    eerie = _delivery_profile({"voice_emotion": "eerie"}, 3, 8, 1.10)

    assert tense_hook["rate"] > calm["rate"]
    assert tense_hook["volume_percent"] > calm["volume_percent"]
    assert eerie["pitch_hz"] < calm["pitch_hz"]
    assert "..." not in _spoken_text("Wait... what happened?", "tense")
