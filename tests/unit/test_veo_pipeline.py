from pathlib import Path

import pytest


def test_veo_prompt_requires_articulation_contact_and_independent_environment():
    from app.agents.video_edit_agent import _veo_motion_prompt

    prompt = _veo_motion_prompt({
        "scene_id": 1, "environment": "1980s Bengaluru street",
        "shots": [{"start": 0, "duration": 6, "action": "walk", "camera": "tracking"}],
    }, 6)
    assert "articulated shoulders" in prompt
    assert "planted-foot contact" in prompt
    assert "independent environmental motion" in prompt
    assert "Camera motion supports the action but is not the only movement" in prompt


def test_veo_provider_rejects_unsupported_duration_without_network(tmp_path):
    from app.video.veo_provider import VeoVideoProvider

    provider = VeoVideoProvider(api_key="not-used")
    with pytest.raises(ValueError, match="4, 6, or 8"):
        provider._generate(
            prompt="test", image=None, output_path=tmp_path / "x.mp4",
            duration_seconds=5, aspect_ratio="16:9", resolution="720p",
            generate_audio=False, person_generation="allow_adult",
            negative_prompt=None, seed=1,
        )


def test_veo_scene_requires_bounded_action_beat(tmp_path):
    from app.agents.video_edit_agent import VideoEditAgent

    image = tmp_path / "frame.jpg"
    image.write_bytes(b"approved-keyframe")
    with pytest.raises(RuntimeError, match="split it into <=8s action beats"):
        VideoEditAgent()._build_veo_scene_clip(
            {"scene_id": 1}, image, None, None, tmp_path / "out.mp4", 8.5, "16:9"
        )


def test_reference_motion_report_rejects_fake_translation_flag():
    report = Path("output/reference_analysis/motion_report.json")
    if not report.is_file():
        pytest.skip("reference video analysis has not been generated")
    import json
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert data["fake_translation_detected"] is False
    assert data["rig_articulation"] > .18
