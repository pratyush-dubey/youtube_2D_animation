"""Build the deterministic bank proof scene from production JSON."""
import json
from pathlib import Path

import bpy
from camera_manager import create_camera
from character_loader import import_character
from environment_manager import build_bank_environment
from lighting_manager import build_lighting
from render_manager import configure


def build_scene(plan, quality):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    fps = int(plan["render"].get("fps", 12 if quality == "PREVIEW" else 24))
    scene.render.fps = fps
    scene.frame_start, scene.frame_end = 1, int(float(plan["duration_seconds"]) * fps)
    configure(scene, plan, quality)
    environment = build_bank_environment(plan["locations"][0].get("period", "1980s"))
    character_spec = plan["characters"][0]
    model_path = character_spec.get("model_path")
    if not model_path:
        raise RuntimeError("Production 3D character provider is not configured.")
    quality_report_path = character_spec.get("quality_report_path")
    if not quality_report_path or not Path(quality_report_path).is_file():
        raise RuntimeError("Character beauty and animation quality report is missing.")
    quality_report = json.loads(Path(quality_report_path).read_text(encoding="utf-8"))
    if not quality_report.get("production_ready"):
        raise RuntimeError("Character has not passed the production beauty and animation gate.")
    character = import_character(model_path)
    validation = {
        "passed": bool(character["armatures"]),
        "armature_count": len(character["armatures"]),
    }
    if not validation["passed"]:
        raise RuntimeError(f"Imported production model is not rigged: {validation}")
    camera = create_camera(fps)
    camera.data.dof.focus_object = character["focus"]
    build_lighting()
    scene["production_metadata"] = str({
        "dramatic_reconstruction": True,
        "rig_validation": validation,
        "environment": environment,
    })
    return scene, {"rig_validation": validation, "environment": environment}
