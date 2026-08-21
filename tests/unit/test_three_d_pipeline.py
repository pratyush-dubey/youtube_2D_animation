from __future__ import annotations

import json
import os
from pathlib import Path


def test_default_style_is_cinematic_toon_3d():
    from app.three_d.styles import DEFAULT_STYLE, resolve_style

    style = resolve_style(None)
    assert DEFAULT_STYLE == "CINEMATIC_TOON_3D"
    assert style["render"]["toon"] is True
    assert style["lighting"]["ambient_occlusion"] is True


def test_action_planner_maps_story_to_ordered_motion():
    from app.three_d.action_planner import ActionPlanner

    actions = ActionPlanner().plan(
        "He slowly walked toward the door and looked back before speaking.", 9, "tense"
    )
    assert [item["action"] for item in actions] == ["walk", "turn", "talk", "look"]
    assert all(item["emotion"] == "tense" for item in actions)
    assert all(item["blend_in"] > 0 for item in actions)


def test_provider_registry_is_vendor_neutral():
    from app.three_d.providers import ProviderCapabilities, ProviderRegistry

    capabilities = ProviderCapabilities(humanoid_rig=True, facial_rig=True)
    registry = ProviderRegistry()
    assert capabilities.humanoid_rig
    assert registry.character is None


def test_bank_proof_plan_is_deterministic_and_disclosed(tmp_path):
    from app.three_d.runner import BlenderRenderProvider
    from tools.render_bank_clerk_3d_proof import build_plan

    plan = build_plan()
    path = tmp_path / "production_plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    result = BlenderRenderProvider(executable=str(tmp_path / "missing.exe")).validate_plan(path)
    assert result["passed"] is True
    assert plan["pipeline"] == "SKELETON_DRIVEN_BLENDER"
    assert "reconstruction" in plan["disclosure"].lower()
    assert sum(shot["duration"] for shot in plan["scenes"][0]["shots"]) == 30


def test_blender_worker_is_modular():
    root = Path(__file__).resolve().parents[2] / "blender_worker"
    expected = {
        "scene_builder.py", "character_loader.py", "rig_manager.py",
        "animation_manager.py", "camera_manager.py", "lighting_manager.py",
        "material_manager.py", "environment_manager.py", "render_manager.py",
    }
    assert expected <= {path.name for path in root.glob("*.py")}


def test_production_character_provider_blocks_without_configuration(monkeypatch):
    from app.config.settings import settings
    from app.providers.character3d.base import CharacterGenerationBlocked
    from app.providers.character3d.factory import create_character3d_provider

    monkeypatch.setattr(settings, "character_3d_provider", "blocked")
    provider = create_character3d_provider()
    assert provider.configured is False
    try:
        provider.generate_from_text({}, Path("unused"))
    except CharacterGenerationBlocked as exc:
        assert str(exc) == "Production 3D character provider is not configured."
    else:
        raise AssertionError("unconfigured production provider must not create a placeholder")


def test_local_provider_accepts_only_a_real_existing_asset(tmp_path):
    from app.providers.character3d.local_provider import LocalCharacter3DProvider

    missing = LocalCharacter3DProvider(tmp_path / "missing.glb")
    assert missing.configured is False
    source = tmp_path / "licensed.glb"
    source.write_bytes(b"glTF" + b"x" * 60_000)
    provider = LocalCharacter3DProvider(source)
    asset = provider.generate_from_text({"character_id": "hero"}, tmp_path / "out")
    assert asset.model_path.exists()
    assert asset.provider == "local_asset"


def test_retired_blender_character_path_contains_no_primitive_constructor():
    source = (Path(__file__).resolve().parents[2] / "blender_worker/character_loader.py").read_text()
    assert "primitive_ico_sphere_add" not in source
    assert "primitive_cube_add" not in source
    assert "Generated character is a procedural placeholder" in source
    scene_builder = (Path(__file__).resolve().parents[2] / "blender_worker/scene_builder.py").read_text()
    assert 'quality_report.get("production_ready")' in scene_builder


def test_blender_render_never_accepts_a_stale_video(monkeypatch, tmp_path):
    from app.three_d.runner import BlenderRenderProvider

    executable = tmp_path / "blender.exe"
    executable.touch()
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    output = tmp_path / "old.mp4"
    output.write_bytes(b"x" * 20_000)
    validation = output.with_suffix(".validation.json")
    validation.write_text('{"technical_passed": true}', encoding="utf-8")
    os.utime(output, (1, 1))
    os.utime(validation, (1, 1))
    monkeypatch.setattr("app.three_d.runner.subprocess.run", lambda *args, **kwargs: None)
    provider = BlenderRenderProvider(str(executable))
    try:
        provider.render(plan, output)
    except RuntimeError as exc:
        assert "did not produce a valid video" in str(exc)
    else:
        raise AssertionError("stale output must never count as a successful render")
