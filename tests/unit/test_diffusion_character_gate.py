from pathlib import Path

import pytest


def test_diffusion_quality_gate_requires_manual_semantic_review(tmp_path):
    from PIL import Image, ImageDraw
    from app.characters.quality import inspect_diffusion_master

    image = Image.new("RGB", (512, 768), "#d8d0c1")
    draw = ImageDraw.Draw(image)
    for index in range(300):
        x = index * 37 % 512; y = index * 71 % 768
        draw.line((x, y, min(511, x + 80), min(767, y + 120)), fill=(index % 255, 40, 120), width=3)
    path = tmp_path / "master.png"; image.save(path)
    report = inspect_diffusion_master(path)
    assert report["manual_review_required"] is True
    assert report["production_approved"] is False
    assert report["semantic_checks"]["hands_visible"] == "manual_review_required"


def test_renderer_hard_fails_when_character_rig_is_missing(tmp_path):
    from PIL import Image, ImageDraw
    from app.characters.errors import CharacterGenerationError
    from app.video.animated_renderer import _World

    scene = {
        "scene_id": 1, "character_name": "Arun", "visual_quality": "DEBUG",
        "shots": [{"id": "1A", "start": 0, "duration": 1, "shot_type": "medium", "action": "idle"}],
    }
    world = _World(scene, 320, 180, Image.new("RGBA", (320, 180), "black"), {}, [], 15)
    with pytest.raises(CharacterGenerationError, match="Primitive fallback is disabled"):
        world.frame(0, 1)
