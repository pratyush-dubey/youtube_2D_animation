"""Blender CLI entry point for provider-model inspection."""
import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bpy  # noqa: E402
from character_loader import import_character  # noqa: E402
from model_validator import validate_imported_character  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    report_path = Path(args.report)
    try:
        character = import_character(args.model)
        report = validate_imported_character(character)
        report["model_format"] = Path(args.model).suffix.removeprefix(".").lower()
    except Exception as exc:
        report = {
            "passed": False,
            "quality_status": "rejected",
            "model_format": Path(args.model).suffix.removeprefix(".").lower(),
            "vertex_count": 0,
            "triangle_count": 0,
            "materials": [],
            "textures": [],
            "rig_status": "rejected",
            "facial_rig_status": "rejected",
            "animation_test_status": "not_tested",
            "rejection_reasons": [str(exc)],
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
