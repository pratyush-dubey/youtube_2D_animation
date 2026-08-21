"""Generate, render, and validate only the strict 10-second 2D/2.5D proof."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))

from app.cinematic.local_art import generate_bank_proof_art
from app.cinematic.motion_validation import analyze_motion, create_debug_video
from app.three_d.runner import find_blender


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("output/cinematic_10s_proof"))
    args = parser.parse_args(); output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    manifest = generate_bank_proof_art(output / "art")
    manifest_path = output / "art" / "asset_manifest.json"
    blender = find_blender()
    if not blender: raise RuntimeError("Blender is required for the 2.5D proof")
    worker = PROJECT_ROOT / "blender_worker" / "cinematic_2d25d_proof.py"
    subprocess.run([blender, "--factory-startup", "--background", "--python", str(worker), "--", "--manifest", str(manifest_path), "--output", str(output)], check=True)
    telemetry = output / "animation_telemetry.json"; frames = output / "frames"
    if not telemetry.is_file() or not (frames / "frame_0150.png").is_file():
        raise RuntimeError("Blender exited without completing the 150-frame proof")
    report = analyze_motion(frames, telemetry, output / "motion_report.json")
    create_debug_video(frames, telemetry, output / "cinematic_10s_debug.mp4")
    result = {
        "status": "passed" if report["success"] else "failed",
        "duration_seconds": 10, "audio": False, "subtitles": False, "cost_inr": 0,
        "art_provider": manifest["generator"],
        "video": str((output / "cinematic_10s_proof.mp4").resolve()),
        "debug_video": str((output / "cinematic_10s_debug.mp4").resolve()),
        "blend": str((output / "cinematic_10s_proof.blend").resolve()),
        "motion_report": str((output / "motion_report.json").resolve()),
    }
    (output / "production_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if report["success"] else 2


if __name__ == "__main__": raise SystemExit(main())
