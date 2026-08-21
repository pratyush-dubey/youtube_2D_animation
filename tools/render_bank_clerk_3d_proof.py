"""Create and render the 30-second Blender proof of concept."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.three_d.action_planner import ActionPlanner  # noqa: E402
from app.three_d.runner import BlenderRenderProvider  # noqa: E402
from app.three_d.styles import DEFAULT_STYLE, resolve_style  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "output" / "bank_clerk_3d_proof"


def build_plan() -> dict:
    narration = (
        "Dramatic reconstruction. In 1980s Bengaluru, a young bank visitor walked "
        "through the entrance, approached the counter, and looked toward a sound off-screen."
    )
    shots = [
        {"id": "01", "start": 0, "duration": 5, "type": "wide", "camera": "dolly"},
        {"id": "02", "start": 5, "duration": 6, "type": "full_body", "camera": "tracking"},
        {"id": "03", "start": 11, "duration": 5, "type": "follow", "camera": "tracking"},
        {"id": "04", "start": 16, "duration": 5, "type": "medium", "camera": "truck"},
        {"id": "05", "start": 21, "duration": 4, "type": "closeup", "camera": "dolly"},
        {"id": "06", "start": 25, "duration": 3, "type": "over_shoulder", "camera": "orbit"},
        {"id": "07", "start": 28, "duration": 2, "type": "wide", "camera": "dolly_out"},
    ]
    return {
        "production_version": 2,
        "pipeline": "SKELETON_DRIVEN_BLENDER",
        "title": "Bank Clerk — 1980s Bengaluru",
        "duration_seconds": 30,
        "disclosure": "Dramatic reconstruction; not authentic archival footage.",
        "characters": [{
            "id": "young_muthappa_rai_reconstruction",
            "name": "Young Muthappa Rai — stylized reconstruction",
            "age_stage": "young",
            "era": "1980s",
            "identity_status": "stylized_reconstruction_requires_verified_reference_for_likeness",
            "height_m": 1.75,
            "clothing": "period-appropriate collared shirt and dark trousers",
            "rig": "standard_humanoid_v1",
        }],
        "locations": [{"id": "bank_1980s_bengaluru", "period": "1980s", "modern_objects": False}],
        "props": ["wooden counter", "ledger books", "chairs", "teller grille"],
        "actions": ActionPlanner().plan(narration, 30, "focused_then_alert"),
        "scenes": [{"id": "bank_sequence", "shots": shots, "emotion": "focused_then_alert"}],
        "style_preset": DEFAULT_STYLE,
        "style": resolve_style(DEFAULT_STYLE),
        "audio": {"narration": narration, "sfx": ["footsteps", "bank_ambience", "offscreen_sound"]},
        "render": {"provider": "blender", "quality": "PREVIEW", "width": 1920, "height": 1080, "fps": 8},
        "quality_checks": {
            "model": ["model_exists", "materials_exist", "humanoid_proportions"],
            "rig": ["required_bones", "walk", "head_turn", "face_controls"],
            "scene": ["environment", "camera", "lights"],
            "animation": ["no_t_pose", "ground_contact", "motion_blending"],
            "render": ["toon_materials", "shadows", "resolution"],
        },
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = OUTPUT_DIR / "production_plan.json"
    plan_path.write_text(json.dumps(build_plan(), indent=2), encoding="utf-8")
    output = OUTPUT_DIR / "bank_clerk_1980s_bengaluru_preview.mp4"
    provider = BlenderRenderProvider()
    print(json.dumps({"blender_available": provider.available(), "plan": str(plan_path)}, indent=2))
    provider.render(plan_path, output, "PREVIEW")
    print(json.dumps({"video": str(output), "validation": str(output.with_suffix('.validation.json'))}, indent=2))


if __name__ == "__main__":
    main()
