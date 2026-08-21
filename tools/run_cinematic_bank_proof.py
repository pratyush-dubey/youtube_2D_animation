"""Plan or run the strict 30-second cinematic 2D/2.5D acceptance proof."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.cinematic.proof import CinematicBankProof  # noqa: E402
from app.llm.ollama_provider import OllamaProvider  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("output/cinematic_bank_proof"))
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--ollama-review", action="store_true")
    args = parser.parse_args()
    director = OllamaProvider(timeout=240) if args.ollama_review else None
    proof = CinematicBankProof(args.output_dir, director=director)
    report = proof.run(plan_only=args.plan_only)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in {"planned", "awaiting_layering"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
