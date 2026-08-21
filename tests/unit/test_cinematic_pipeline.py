from pathlib import Path

import pytest


def test_bank_proof_has_six_shot_specific_compositions():
    from app.cinematic.quality import inspect_plan
    from app.cinematic.shot_planner import ShotPlanner

    character, shots = ShotPlanner().plan_bank_proof()
    assert character.fictional is True
    assert [shot.start for shot in shots] == [0, 5, 10, 15, 20, 25]
    assert [shot.artwork_kind for shot in shots] == [
        "environment", "full_body", "medium", "medium", "closeup", "sitting"
    ]
    assert inspect_plan(shots)["passed"] is True
    assert len({shot.image_prompt for shot in shots}) == 6


def test_25d_shots_use_distinct_parallax_speeds():
    from app.cinematic.shot_planner import ShotPlanner

    _, shots = ShotPlanner().plan_bank_proof()
    for shot in shots:
        if shot.animation_mode == "2.5d":
            assert len({layer.parallax_speed for layer in shot.layers}) > 1


def test_primary_image_provider_never_uses_placeholder(monkeypatch, tmp_path):
    from app.cinematic.image_provider import ImageGenerationBlocked, get_cinematic_image_provider

    monkeypatch.delenv("CINEMATIC_IMAGE_PROVIDER", raising=False)
    provider = get_cinematic_image_provider(tmp_path)
    assert provider.name == "unconfigured"
    with pytest.raises(ImageGenerationBlocked, match="Image generation provider is not configured"):
        provider.generate_shot("test", tmp_path / "shot.png")


def test_zero_cost_mode_blocks_paid_gemini_image(monkeypatch, tmp_path):
    from app.cinematic.image_provider import get_cinematic_image_provider

    monkeypatch.setenv("CINEMATIC_IMAGE_PROVIDER", "gemini_image")
    monkeypatch.setenv("ZERO_COST_MODE", "true")
    provider = get_cinematic_image_provider(tmp_path)
    assert provider.configured is False
    assert "ZERO_COST_MODE" in provider.reason


def test_production_puppet_rejects_monolithic_character():
    from app.cinematic.puppet import PuppetPart, PuppetRig

    with pytest.raises(ValueError, match="missing articulated parts"):
        PuppetRig("person", {"torso": PuppetPart("torso", "missing.png", (0.5, 0.5), (0, 0), None, 0.5)}, (1920, 1080))


def test_walk_cycle_articulates_limbs_and_advances_without_rigid_png_slide():
    from app.cinematic.motion import PuppetAnimator

    first = PuppetAnimator().frame("walk", 0.1)
    second = PuppetAnimator().frame("walk", 0.25)
    assert first.root.x != second.root.x
    assert first.parts["upper_leg_left"].rotation != second.parts["upper_leg_left"].rotation
    assert first.parts["upper_arm_right"].rotation != second.parts["upper_arm_right"].rotation
    assert first.contact_shadow_scale != second.contact_shadow_scale


def test_bilingual_subtitles_are_time_aligned(tmp_path):
    from app.cinematic.subtitles import SubtitleCue, write_srt

    cue = SubtitleCue(0, 2.5, "He entered the bank.", "वह बैंक में दाखिल हुआ।")
    output = write_srt([cue], tmp_path / "bilingual.srt", "bilingual")
    text = output.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:02,500" in text
    assert cue.english in text and cue.hindi in text
