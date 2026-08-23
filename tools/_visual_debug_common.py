"""Shared reporting utilities for ordered visual forensic commands."""
from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "debug_visual_test"
SHOT = OUTPUT / "shot_001.png"
REPORT = ROOT / "output" / "visual_debug_report.json"


def record(name: str, status: str, *, project_id: str = "debug_visual_test", error: Exception | None = None, **details) -> None:
    try:
        report = json.loads(REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {
            "project_id": project_id,
            "direct_comfyui": {"status": "NOT_RUN"},
            "provider": {"status": "NOT_RUN"},
            "visual_director": {"status": "NOT_RUN"},
            "background_worker": {"status": "NOT_RUN"},
            "browser": {"status": "NOT_RUN"},
            "failure_stage": None, "failure_reason": None, "traceback": None,
        }
    report[name] = {"status": status, "timestamp": datetime.now(UTC).isoformat(), **details}
    if error is not None:
        report.update(
            failure_stage=name, failure_reason=f"{type(error).__name__}: {error}",
            traceback="".join(traceback.format_exception(type(error), error, error.__traceback__)),
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

