"""Blender background entry point. Arguments follow `--`."""
import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_manager import render_frames  # noqa: E402
from scene_builder import build_scene  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--quality", choices=("PREVIEW", "FINAL"), default="PREVIEW")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    scene, validation = build_scene(plan, args.quality)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    render_frames(scene, output, scene.render.fps)
    report = output.with_suffix(".validation.json")
    report.write_text(json.dumps({
        "technical_passed": True,
        "production_ready": False,
        "production_blockers": [
            "procedural test character must be replaced by a topology-quality Character3DProvider asset",
            "real-person likeness requires verified licensed references",
            "FINAL Eevee toon render and deformation review are still required",
            "foot IK, hand IK, cloth, and historical art-detail passes are not yet complete",
        ],
        **validation,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
