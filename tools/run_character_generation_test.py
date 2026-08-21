"""Generate and validate one genuine 3D character before any scene rendering."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.providers.character3d import (  # noqa: E402
    CharacterGenerationBlocked,
    create_character3d_provider,
)
from app.providers.character3d.base import BLOCKED_MESSAGE  # noqa: E402
from app.three_d.runner import BlenderRenderProvider  # noqa: E402

OUTPUT_DIR = Path("output/character_generation_test")


def blocked_report(provider: str, reason: str) -> dict:
    return {
        "model_format": "",
        "vertex_count": 0,
        "triangle_count": 0,
        "materials": [],
        "textures": [],
        "rig_status": "blocked",
        "facial_rig_status": "blocked",
        "animation_test_status": "blocked",
        "provider": provider,
        "generation_status": "blocked",
        "quality_status": "blocked",
        "rejection_reasons": [reason],
        "required_outputs_created": [],
        "production_ready": False,
    }


def write_report(report: dict, output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "character_quality_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character-id", default="bank_clerk_adult")
    parser.add_argument(
        "--description",
        default=(
            "35-year-old Indian man, lean natural proportions, detailed expressive face, "
            "short side-parted black hair, 1980s pale cotton bank shirt, tailored dark trousers, "
            "leather shoes, stylized cinematic animated-film design"
        ),
    )
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    provider = create_character3d_provider()
    if not provider.configured:
        report_path = write_report(blocked_report(provider.name, BLOCKED_MESSAGE), args.output_dir)
        print(f"BLOCKED: {BLOCKED_MESSAGE}")
        print(f"Report: {report_path}")
        return 2
    references = [Path(value) for value in args.reference]
    specification = {
        "character_id": args.character_id,
        "description": args.description,
        "style": "cinematic_stylized_3d",
        "height": 1.76,
    }
    try:
        if references:
            asset = provider.generate_from_reference(specification, references, args.output_dir / "cache")
        else:
            asset = provider.generate_from_text(specification, args.output_dir / "cache")
        canonical = args.output_dir / f"character_model.{asset.format}"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        if asset.model_path.resolve() != canonical.resolve():
            shutil.copy2(asset.model_path, canonical)
        blender_report = BlenderRenderProvider().validate_character_model(
            canonical, args.output_dir / "blender_model_validation.json"
        )
        report = {
            **blender_report,
            "provider": provider.name,
            "generation_status": "generated",
            "quality_status": blender_report.get("quality_status", "rejected"),
            "production_ready": False,
            "required_outputs_created": [canonical.name, "blender_model_validation.json"],
        }
        if blender_report.get("passed"):
            report["quality_status"] = "awaiting_beauty_and_animation_tests"
            report["rejection_reasons"] = [
                "Beauty-sheet, idle, walk, and facial-reaction renders must pass visual review."
            ]
        write_report(report, args.output_dir)
        print(f"Model quality status: {report['quality_status']}")
        return 0 if report.get("production_ready") else 3
    except CharacterGenerationBlocked as exc:
        write_report(blocked_report(provider.name, str(exc)), args.output_dir)
        print(f"BLOCKED: {exc}")
        return 2
    except Exception as exc:
        report = blocked_report(provider.name, str(exc))
        report["generation_status"] = "failed"
        report["quality_status"] = "rejected"
        write_report(report, args.output_dir)
        print(f"REJECTED: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
