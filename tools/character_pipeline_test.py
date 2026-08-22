"""Gate runner: never advances a rejected diffusion character downstream."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = ROOT / "output" / "character_generation_test"


def main() -> int:
    image = TEST_DIR / "arun_diffusion_test.png"
    report_path = TEST_DIR / "quality_report.json"
    if not image.is_file() or not report_path.is_file():
        print("DIFFUSION CHARACTER: FAIL - required PNG or quality report is missing")
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    approved = bool(report.get("technical_pass") and report.get("production_approved"))
    if not approved:
        problems = ", ".join(report.get("problems") or ["manual approval missing"])
        print(f"DIFFUSION CHARACTER: FAIL - {problems}")
        print("BACKGROUND REMOVAL: NOT RUN")
        print("SEGMENTATION: NOT RUN")
        print("RIG: NOT RUN")
        print("Primitive fallback is disabled. Pipeline stopped at the quality gate.")
        return 2
    # This milestone deliberately does not execute downstream work implicitly.
    print("DIFFUSION CHARACTER: PASS")
    print("BACKGROUND REMOVAL: READY, NOT RUN")
    print("SEGMENTATION: READY, NOT RUN")
    print("RIG: READY, NOT RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
