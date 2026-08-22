"""Small in-process job manager for the local Character Studio webpage."""
from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from app.characters.package import CharacterPackageBuilder, character_bible_from_prompt
from app.characters.provider import create_character_image_provider
from app.characters.errors import LOCAL_DIFFUSION_FAILURE


logger = structlog.get_logger(__name__)
STAGES = (
    ("character_specification", "Character specification"),
    ("prompt_preparation", "Prompt preparation"),
    ("comfyui_submission", "ComfyUI submission"),
    ("image_generation", "Image generation"),
    ("image_retrieval", "Image retrieval"),
    ("quality_check", "Quality check"),
    ("background_removal", "Background removal"),
    ("character_asset", "Character asset creation"),
)


def character_library_root() -> Path:
    configured = os.getenv("CHARACTER_LIBRARY_DIR", r"D:\AI_VIDEO_GENERATOR\character_library")
    return Path(configured).expanduser().resolve()


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return (slug[:48] or "character")


class CharacterStudioJobs:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="character-studio")

    def service_status(self) -> dict[str, Any]:
        provider = create_character_image_provider()
        return {
            "ready": provider.configured,
            "provider": provider.name,
            "model": provider.model,
            "output_root": str(character_library_root()),
            "message": "Local image generator is ready" if provider.configured else "ComfyUI is not running. Start the studio with start_character_studio.bat.",
        }

    def create(self, name: str, description: str, mode: str) -> dict[str, Any]:
        with self._lock:
            if any(job["status"] in {"queued", "running"} for job in self._jobs.values()):
                raise RuntimeError("A character is already generating. Please wait for it to finish.")
            job_id = uuid.uuid4().hex[:12]
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = character_library_root() / f"{safe_slug(name)}_{stamp}"
            job = {
                "id": job_id,
                "name": " ".join(name.split()),
                "description": " ".join(description.split()),
                "mode": mode,
                "status": "queued",
                "message": "Waiting to start",
                "completed": 0,
                "total": 1 if mode == "master" else 12,
                "percent": 0,
                "output_dir": str(output_dir),
                "images": [],
                "error": None,
                "failure": None,
                "active_stage": "character_specification",
                "stages": [
                    {"id": stage_id, "label": label, "status": "active" if index == 0 else "pending"}
                    for index, (stage_id, label) in enumerate(STAGES)
                ],
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._jobs[job_id] = job
            logger.info(
                "CHARACTER_GENERATION_REQUEST",
                stage="character_api",
                job_id=job_id,
                mode=mode,
                name_length=len(job["name"]),
                description_length=len(job["description"]),
                output_dir=str(output_dir),
            )
            self._executor.submit(self._run, job_id)
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(next(reversed(self._jobs.values()))) if self._jobs else None

    def output_file(self, job_id: str, relative_path: str) -> Path | None:
        job = self.get(job_id)
        if not job:
            return None
        root = Path(job["output_dir"]).resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target if target.is_file() else None

    def open_folder(self, job_id: str) -> str:
        job = self.get(job_id)
        if not job:
            raise KeyError(job_id)
        path = Path(job["output_dir"]).resolve()
        root = character_library_root()
        path.relative_to(root)
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return str(path)

    def _update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            self._jobs[job_id].update(values)

    def _set_stage(self, job_id: str, stage_id: str, status: str, message: str | None = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            stages = [dict(stage) for stage in job["stages"]]
            for stage in stages:
                if stage["id"] == stage_id:
                    stage["status"] = status
                    if message:
                        stage["message"] = message
            finished = sum(stage["status"] in {"completed", "skipped"} for stage in stages)
            job.update(
                stages=stages,
                active_stage=stage_id if status == "active" else job.get("active_stage"),
                percent=round(finished / len(stages) * 100),
                message=message or job.get("message"),
            )

    def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        output_dir = Path(job["output_dir"])
        try:
            def comfy_progress(event: str, details: dict[str, Any]) -> None:
                if event == "submitting":
                    self._set_stage(job_id, "prompt_preparation", "completed")
                    self._set_stage(job_id, "comfyui_submission", "active", "Submitting workflow to ComfyUI")
                elif event == "generating":
                    self._set_stage(job_id, "comfyui_submission", "completed")
                    self._set_stage(job_id, "image_generation", "active", "Generating image in ComfyUI")
                elif event == "retrieving":
                    self._set_stage(job_id, "image_generation", "completed")
                    self._set_stage(job_id, "image_retrieval", "active", "Retrieving generated PNG")
                elif event == "saved":
                    self._set_stage(job_id, "image_retrieval", "completed")
                    self._set_stage(job_id, "quality_check", "active", "Checking generated PNG")

            provider = create_character_image_provider(progress_callback=comfy_progress)
            if not provider.configured:
                raise RuntimeError(LOCAL_DIFFUSION_FAILURE + " ComfyUI is unreachable at the configured localhost URL.")
            self._update(job_id, status="running", message="Preparing character specification")

            def progress(message: str, completed: int, total: int) -> None:
                images = self._image_list(output_dir)
                self._update(job_id, message=message, completed=completed, total=total, images=images)

            bible = character_bible_from_prompt(job["name"], job["description"])
            self._set_stage(job_id, "character_specification", "completed")
            self._set_stage(job_id, "prompt_preparation", "active", "Preparing diffusion prompt")
            builder = CharacterPackageBuilder(output_dir, provider=provider, progress_callback=progress)
            report = builder.generate_master_only(bible) if job["mode"] == "master" else builder.run(bible)
            self._set_stage(job_id, "quality_check", "completed")
            self._set_stage(job_id, "background_removal", "skipped", "Not required for the master-image connectivity test")
            self._set_stage(job_id, "character_asset", "active", "Creating canonical character asset")
            canonical = self._save_canonical(job, output_dir, provider)
            self._set_stage(job_id, "character_asset", "completed")
            status = "complete" if report.get("status") == "manual_review_required" else report.get("status", "complete")
            self._update(
                job_id,
                status=status,
                message="Generation finished — inspect the images before production use",
                percent=100,
                images=self._image_list(output_dir),
                report=report,
                canonical_output=str(canonical),
            )
            logger.info("CHARACTER_GENERATION_RESPONSE", stage="character_api_job", job_id=job_id, status=status, output=str(canonical))
        except Exception as exc:
            message = " ".join(str(exc).split())
            current = self.get(job_id) or {}
            stage = current.get("active_stage", "character_api")
            self._set_stage(job_id, stage, "failed", "Generation failed")
            failure = {"stage": stage, "error": message[:2000], "code": type(exc).__name__}
            self._update(job_id, status="failed", message="Generation failed", error=message[:2000], failure=failure, images=self._image_list(output_dir))
            logger.error("CHARACTER_GENERATION_ERROR", stage=stage, job_id=job_id, error=message[:2000], error_type=type(exc).__name__)

    @staticmethod
    def _save_canonical(job: dict[str, Any], output_dir: Path, provider: Any) -> Path:
        source = output_dir / "master" / "front.png"
        if not source.is_file():
            raise RuntimeError("Generated PNG was not found after ComfyUI completed.")
        canonical_dir = character_library_root() / safe_slug(job["name"]) / "master"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        target = canonical_dir / "front.png"
        shutil.copy2(source, target)
        last_generation = getattr(getattr(provider, "client", None), "last_generation", {})
        workflow = last_generation.get("workflow") or (
            json.loads(provider.workflow.read_text(encoding="utf-8")) if getattr(provider, "workflow", None) else {}
        )
        sampler = workflow.get("3", {}).get("inputs", {})
        manifest = {
            "provider": provider.name,
            "model": provider.model,
            "seed": sampler.get("seed", 19850317),
            "prompt": job["description"],
            "negative_prompt": workflow.get("7", {}).get("inputs", {}).get("text", ""),
            "resolution": [
                workflow.get("5", {}).get("inputs", {}).get("width", 512),
                workflow.get("5", {}).get("inputs", {}).get("height", 768),
            ],
            "steps": sampler.get("steps", 12),
            "sampler": sampler.get("sampler_name", "dpmpp_2m"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "source": str(source),
        }
        (canonical_dir.parent / "generation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return target

    @staticmethod
    def _image_list(output_dir: Path) -> list[str]:
        if not output_dir.is_dir():
            return []
        return [path.relative_to(output_dir).as_posix() for path in sorted(output_dir.rglob("*.png"))]


character_studio_jobs = CharacterStudioJobs()
