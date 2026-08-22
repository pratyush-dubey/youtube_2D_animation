"""Build only the canonical character package; never renders animation/video."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from app.characters.package import CharacterPackageBuilder, default_arun_bible, plan_arun_with_ollama


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", type=Path, default=Path(r"D:\AI_VIDEO_GENERATOR\character_library\arun"))
    parser.add_argument("--no-ollama", action="store_true", help="Use the deterministic built-in fictional specification")
    parser.add_argument("--master-only", action="store_true", help="Generate only the gated front master for inspection")
    args = parser.parse_args()
    if args.no_ollama:
        bible = default_arun_bible()
    else:
        try:
            bible = plan_arun_with_ollama()
        except Exception as exc:
            bible = default_arun_bible()
            bible["specification_source"] = {"provider": "ollama", "status": "invalid_or_unavailable", "error": str(exc), "cost_inr": 0}
    builder = CharacterPackageBuilder(args.output_dir)
    report = builder.generate_master_only(bible=bible) if args.master_only else builder.run(bible=bible)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "manual_review_required" else 2


if __name__ == "__main__": raise SystemExit(main())
