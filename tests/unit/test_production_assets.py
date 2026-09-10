from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_art_direction_defaults_to_cinematic_illustration():
    from app.images.production_assets import ArtDirection

    direction = ArtDirection()
    assert direction.style == "cinematic_2d_illustration"
    assert direction.anatomy == "natural"
    assert "triangle trees" in direction.avoid


def test_flat_geometric_asset_is_rejected(tmp_path):
    from app.images.production_assets import evaluate_asset

    path = tmp_path / "flat.png"
    Image.new("RGB", (1200, 900), "#123456").save(path)

    report = evaluate_asset(path, "environment")

    assert report.passed is False
    assert "detail_entropy" in report.problems
    assert "edge_detail" in report.problems


def test_checked_in_illustrated_assets_pass_quality_gate():
    from app.images.production_assets import evaluate_asset

    environment = PROJECT_ROOT / "assets/production/forest_encounter/environment/forest_master.png"
    character = PROJECT_ROOT / "assets/production/forest_encounter/characters/ravi/reference.png"

    assert evaluate_asset(environment, "environment").passed
    assert evaluate_asset(character, "character").passed


def test_character_with_unremoved_backdrop_prop_is_rejected(tmp_path):
    """A provider that ignores 'plain background' and paints a whole room/
    poster scene must not pass just because *some* pixels got cut - the rig
    extraction downstream assumes a standing-figure bbox and produces torn,
    misplaced body parts otherwise (see production_assets.py's
    silhouette_shape check)."""
    from app.images.production_assets import evaluate_asset

    path = tmp_path / "prop_scene.png"
    # A wide, near-square opaque "canvas propped against a wall" region with
    # only a small person-shaped notch of transparency - width/height close
    # to 1.0, nothing like a standing human silhouette (~0.15-0.65).
    image = Image.new("RGBA", (1000, 1200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 100, 950, 1100), fill=(210, 210, 205, 255))
    for x in range(50, 950, 15):
        draw.line((x, 100, x, 1100), fill=(190 + x % 20, 190 + x % 20, 185, 255), width=2)
    draw.ellipse((450, 200, 550, 300), fill=(200, 150, 120, 255))
    draw.rectangle((470, 300, 530, 700), fill=(220, 220, 220, 255))
    path_ = path
    image.save(path_)

    report = evaluate_asset(path_, "character")

    assert report.passed is False
    assert "silhouette_shape" in report.problems


def test_background_removal_and_rig_extraction(tmp_path):
    from app.images.production_assets import extract_character_rig, remove_subject_background

    source = Image.new("RGB", (1000, 1200), "white")
    draw = ImageDraw.Draw(source)
    draw.ellipse((350, 90, 650, 390), fill="#8b5a3c")
    draw.rounded_rectangle((250, 340, 750, 850), 80, fill="#24553d")
    draw.rectangle((290, 820, 470, 1160), fill="#202c35")
    draw.rectangle((530, 820, 710, 1160), fill="#202c35")
    raw = tmp_path / "raw.png"
    cutout = tmp_path / "cutout.png"
    source.save(raw)

    remove_subject_background(raw, cutout)
    assert Image.open(cutout).getchannel("A").getextrema() == (0, 255)

    manifest = extract_character_rig(cutout, tmp_path / "rig")
    assert manifest.exists()
    rig = __import__("json").loads(manifest.read_text(encoding="utf-8"))
    assert rig["rig_version"] == 3
    assert rig["representation"] == "segmented_artwork_skeleton"
    assert {"hips", "knee_l", "ankle_r", "shoulder_l"} <= set(rig["joints"])
    assert {"head", "torso", "left_upper_leg", "left_lower_leg", "right_upper_arm"} <= set(rig["parts"])
    assert "mouth" in rig["joints"]


def test_provider_reports_reference_limitations(tmp_path):
    from app.images.provider_interface import get_production_image_provider

    provider = get_production_image_provider("placeholder")
    assert provider.capabilities.reference_images is False
    with pytest.raises(NotImplementedError):
        provider.generate_pose("walking", tmp_path / "ref.png", tmp_path / "pose.png")


def test_production_generation_never_uses_primitive_fallback(tmp_path, monkeypatch):
    from app.agents.asset_agent import AssetAgent

    monkeypatch.setattr("app.config.settings.settings.image_provider", "placeholder")
    with pytest.raises(RuntimeError, match="primitive fallback is disabled"):
        AssetAgent()._generate_image(
            "illustrated forest", tmp_path / "scene.jpg", 1, visual_quality="PRODUCTION"
        )
