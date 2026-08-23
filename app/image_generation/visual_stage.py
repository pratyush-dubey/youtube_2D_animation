"""Audit, validation, and failure artifacts for the production visual stage."""
from __future__ import annotations

import json
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, UnidentifiedImageError


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class VisualStageLog:
    """Write one JSON object per line so partial/crashed runs remain readable."""

    def __init__(self, output_dir: Path, project_id: str):
        self.project_id = project_id
        self.started = time.perf_counter()
        self.path = output_dir / "logs" / "visual_generation.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event: str,
        *,
        scene_id: str | int | None = None,
        shot_id: str | int | None = None,
        duration: float | None = None,
        error: str | None = None,
        **details: Any,
    ) -> None:
        record = {
            "event": event,
            "project_id": self.project_id,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "timestamp": utc_now(),
            "duration": round(duration if duration is not None else time.perf_counter() - self.started, 3),
            "error": error,
            **details,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


class VisualTrace:
    """Forensic, grep-friendly markers for one visual worker execution."""

    MARKERS = {
        1: "ENTER VISUALS", 2: "LOAD PROJECT", 3: "LOAD SCRIPT",
        4: "LOAD CHARACTER MANIFEST", 5: "CREATE SCENE PLAN",
        6: "CREATE SHOT PLAN", 7: "VISUAL PROMPTS CREATED",
        8: "START IMAGE PROVIDER", 9: "COMFYUI HEALTH CHECK",
        10: "COMFYUI WORKFLOW CREATED", 11: "SUBMIT COMFYUI PROMPT",
        12: "COMFYUI PROMPT ID RECEIVED", 13: "WAIT FOR COMFYUI",
        14: "COMFYUI COMPLETE", 15: "DOWNLOAD IMAGE",
        16: "IMAGE VALIDATED", 17: "SAVE IMAGE", 18: "UPDATE DATABASE",
        19: "VISUALS COMPLETE",
    }

    def __init__(self, output_dir: Path, project_id: str):
        self.output_dir = output_dir
        self.project_id = project_id
        self.started = time.perf_counter()
        self.path = output_dir / "logs" / "visual_generation.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def mark(self, number: int, *, scene_id=None, shot_id=None, **details: Any) -> None:
        payload = {
            "timestamp": utc_now(), "project_id": self.project_id,
            "scene_id": scene_id, "shot_id": shot_id,
            "duration_ms": round((time.perf_counter() - self.started) * 1000, 3),
            **details,
        }
        line = f"[VISUAL-TRACE {number:03d}] {self.MARKERS[number]} | " + json.dumps(payload, ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def write_visual_exception(
    output_dir: Path, project_id: str, exc: Exception,
    *, scene_id=None, shot_id=None, stage: str = "visuals",
) -> Path:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    final = frames[-1] if frames else None
    payload = {
        "exception_type": type(exc).__name__, "exception_message": str(exc),
        "traceback": tb, "file": final.filename if final else None,
        "line": final.lineno if final else None, "stage": stage,
        "project_id": project_id, "scene_id": scene_id, "shot_id": shot_id,
        "timestamp": utc_now(),
    }
    path = output_dir / "logs" / "visual_exception.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def validate_image(path: Path, width: int, height: int) -> dict[str, Any]:
    """Reject missing, corrupt, wrong-size, blank, or transparent image output."""
    if not path.is_file():
        raise ValueError(f"Generated image does not exist: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"Generated image is empty: {path}")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError(f"Generated image format is {image.format}; expected PNG or JPEG")
            if image.size != (width, height):
                raise ValueError(f"Generated image size is {image.size}; expected {(width, height)}")
            if "A" in image.getbands() and image.getchannel("A").getextrema()[1] == 0:
                raise ValueError("Generated image is completely transparent")
            rgb = image.convert("RGB")
            extrema = rgb.getextrema()
            if all(low == high for low, high in extrema):
                raise ValueError("Generated image is blank (single solid color)")
            # A bounding box against the top-left pixel catches flat images even
            # when their channels have different constant values.
            flat = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
            if ImageChops.difference(rgb, flat).getbbox() is None:
                raise ValueError("Generated image is blank")
            return {"path": str(path.resolve()), "bytes": size, "format": image.format, "width": width, "height": height}
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Generated image is corrupt or unreadable: {exc}") from exc


def write_failure_report(
    output_dir: Path,
    exc: Exception,
    *,
    scene_id: str | int | None = None,
    shot_id: str | int | None = None,
    retry_count: int = 0,
    prompt_id: str | None = None,
    provider: str = "comfyui_local",
) -> Path:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    final = frames[-1] if frames else None
    details = getattr(exc, "details", None)
    report = {
        "stage": "visuals",
        "status": "failed",
        "scene_id": scene_id,
        "shot_id": shot_id,
        "provider": provider,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "http_status": getattr(exc, "http_status", None),
        "comfyui_prompt_id": prompt_id or getattr(exc, "prompt_id", None),
        "retry_count": retry_count,
        "timestamp": utc_now(),
        "traceback": tb,
        "file": final.filename if final else None,
        "line": final.lineno if final else None,
    }
    if details:
        report["comfyui_error"] = details
    path = output_dir / "reports" / "visual_failure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(path)
    return path
