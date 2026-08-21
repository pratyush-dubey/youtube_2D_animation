"""Host-side Blender worker launcher and resumable render provider."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from app.config.settings import settings


class BlenderRenderProvider:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or find_blender()

    def available(self) -> bool:
        return bool(self.executable and Path(self.executable).exists())

    def render(self, plan_path: Path, output_path: Path, quality: str = "PREVIEW") -> Path:
        if not self.available():
            raise RuntimeError("Blender is not installed; install Blender and set BLENDER_PATH")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = time.time()
        validation_path = output_path.with_suffix(".validation.json")
        worker = Path(__file__).resolve().parents[2] / "blender_worker" / "worker.py"
        command = [
            str(self.executable), "--background", "--python-exit-code", "1",
            "--python", str(worker), "--",
            "--plan", str(plan_path.resolve()), "--output", str(output_path.resolve()),
            "--quality", quality.upper(),
        ]
        subprocess.run(command, check=True)
        if (
            not output_path.exists()
            or output_path.stat().st_size < 10_000
            or output_path.stat().st_mtime < started_at
            or not validation_path.exists()
            or validation_path.stat().st_mtime < started_at
        ):
            raise RuntimeError(f"Blender did not produce a valid video: {output_path}")
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        if not validation.get("technical_passed"):
            raise RuntimeError(f"Blender render failed validation: {validation_path}")
        return output_path

    def validate_plan(self, plan_path: Path) -> dict:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        required = {"characters", "locations", "scenes", "style", "render"}
        missing = sorted(required - set(plan))
        return {"passed": not missing, "missing": missing}

    def validate_character_model(self, model_path: Path, report_path: Path) -> dict:
        if not self.available():
            raise RuntimeError("Blender is not installed; install Blender and set BLENDER_PATH")
        worker = Path(__file__).resolve().parents[2] / "blender_worker" / "validate_character.py"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.executable), "--background", "--python-exit-code", "2",
            "--python", str(worker), "--",
            "--model", str(model_path.resolve()), "--report", str(report_path.resolve()),
        ]
        completed = subprocess.run(command, check=False)
        if not report_path.exists():
            raise RuntimeError(f"Blender model validation produced no report (exit {completed.returncode})")
        return json.loads(report_path.read_text(encoding="utf-8"))


def find_blender() -> str:
    configured = str(getattr(settings, "blender_path", "") or "").strip()
    candidates = [configured, shutil.which("blender") or ""]
    root = Path("C:/Program Files/Blender Foundation")
    if root.exists():
        candidates.extend(str(path) for path in sorted(root.glob("Blender */blender.exe"), reverse=True))
    project_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        str(path)
        for path in sorted(project_root.glob(".tools/blender/**/blender.exe"), reverse=True)
    )
    return next((path for path in candidates if path and Path(path).exists()), "")
