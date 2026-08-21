"""
Projects router — CRUD + pipeline lifecycle for video projects.

Routes (all under /api prefix added in app factory):
  POST /projects              — create + optionally queue pipeline
  GET  /projects              — list projects
  GET  /projects/{id}         — project detail + pipeline status
  POST /projects/{id}/run     — (re)run pipeline
  GET  /projects/{id}/status  — lightweight status poll
  POST /projects/{id}/approve — human gate: publish private → public
  POST /projects/{id}/publish — alias for approve (spec-compliant name)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Request / Response models ─────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=300)
    language: str = Field("English")
    style: str = Field("documentary")
    target_duration_seconds: int = Field(480, ge=60, le=3600)
    aspect_ratio: str = Field("16:9")
    niche: str | None = Field(None, description="Niche preset (science|space|history|tech|psychology)")
    run_pipeline: bool = Field(True, description="Start the full pipeline immediately")


class SceneEditRequest(BaseModel):
    """Editable production fields; omitted values leave other components intact."""
    duration_seconds: float | None = Field(None, ge=1.0, le=120.0)
    emotion: str | None = None
    camera: str | None = None
    animation: str | None = None
    expression: str | None = None
    voice_emotion: str | None = None
    sfx: list[str] | None = None
    shots: list[dict] | None = None
    layers: list[dict] | None = None
    render_quality: str | None = Field(None, pattern="^(DRAFT|PREVIEW|FINAL)$")


class RegenerateComponentRequest(SceneEditRequest):
    run_pipeline: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seo_title_from_disk(output_dir: Path) -> str | None:
    seo_path = output_dir / "seo.json"
    if seo_path.exists():
        try:
            return json.loads(seo_path.read_text())["best_title"]
        except Exception:
            pass
    return None


def _active_job(project_id: str) -> dict | None:
    """Return the most recent in-memory job for a project (fast cache)."""
    from app.api.job_store import job_store
    return job_store.get_latest_for_project(project_id)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=202)
def create_project(req: CreateProjectRequest):
    """Create a new video project and optionally start the full pipeline."""
    from app.database.models import Project
    from app.database.session import get_session

    project_id = str(uuid.uuid4())[:8]

    topic = req.topic
    style = req.style
    duration = req.target_duration_seconds
    if req.niche:
        from app.scheduler.niche_config import get_niche_config
        nc = get_niche_config(req.niche)
        style = style or nc.style
        duration = duration or nc.target_duration_seconds

    with get_session() as s:
        s.add(Project(
            id=project_id,
            topic=topic,
            language=req.language,
            target_duration_seconds=duration,
            style=style,
            aspect_ratio=req.aspect_ratio,
            status="created",
        ))

    job_id: str | None = None
    if req.run_pipeline:
        from app.api.job_runner import submit_pipeline_job
        job_id = submit_pipeline_job(project_id, topic, req.language,
                                     duration, style, req.aspect_ratio)

    return {
        "project_id": project_id,
        "job_id": job_id,
        "status": "queued" if job_id else "created",
        "message": (
            "Pipeline queued. Poll /api/jobs/{job_id} for progress."
            if job_id else "Project created. POST /api/projects/{id}/run to start."
        ),
    }


@router.get("")
def list_projects(limit: int = 20, offset: int = 0):
    """List all projects, most recent first."""
    from app.database.models import Project as ProjModel
    from app.database.session import get_session
    with get_session() as s:
        rows = (
            s.query(ProjModel)
            .order_by(ProjModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "project_id": r.id,
                "topic": r.topic,
                "status": r.status,
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in rows
        ]


@router.get("/{project_id}")
def get_project(project_id: str):
    """Full project detail including pipeline stage summary."""
    from app.database.models import Project as ProjModel
    from app.database.session import get_session
    from app.pipeline.state import PipelineState

    with get_session() as s:
        row = s.query(ProjModel).filter_by(id=project_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        proj = {
            "project_id": row.id,
            "topic": row.topic,
            "status": row.status,
            "created_at": str(row.created_at) if row.created_at else None,
        }

    state = PipelineState(project_id)
    output_dir = Path(settings.output_dir) / project_id
    video_path = output_dir / "final.mp4"
    thumb_path = output_dir / "thumbnail.jpg"

    return {
        **proj,
        "pipeline_stages": state.get_summary(),
        "output_dir": str(output_dir),
        "video_path": str(video_path) if video_path.exists() else None,
        "thumbnail_path": str(thumb_path) if thumb_path.exists() else None,
        "seo_title": _seo_title_from_disk(output_dir),
        "active_job": _active_job(project_id),
    }


@router.post("/{project_id}/run", status_code=202)
def run_project(project_id: str):
    """(Re)run the full pipeline for an existing project."""
    from app.database.models import Project as ProjModel
    from app.database.session import get_session

    with get_session() as s:
        row = s.query(ProjModel).filter_by(id=project_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        topic    = row.topic
        language = row.language or "English"
        duration = row.target_duration_seconds or 480
        style    = row.style or "documentary"
        aspect   = row.aspect_ratio or "16:9"

    from app.api.job_runner import submit_pipeline_job
    job_id = submit_pipeline_job(project_id, topic, language, duration, style, aspect)
    return {"project_id": project_id, "job_id": job_id, "status": "queued"}


@router.get("/{project_id}/status")
def project_status(project_id: str):
    """Lightweight stage-level status poll."""
    from app.pipeline.state import PipelineState
    state = PipelineState(project_id)
    return {"project_id": project_id, "stages": state.get_summary()}


@router.get("/{project_id}/production-plan")
def get_production_plan(project_id: str):
    """Return the editable scene/shot/layer/keyframe plan used for rendering."""
    output_dir = Path(settings.output_dir) / project_id
    plan_path = output_dir / "production_plan.json"
    storyboard_path = output_dir / "storyboard.json"
    source = plan_path if plan_path.exists() else storyboard_path
    if not source.exists():
        raise HTTPException(status_code=404, detail="Production plan has not been generated")
    data = json.loads(source.read_text(encoding="utf-8"))
    scenes = data.get("scenes", [])
    return {
        "project_id": project_id,
        "production_version": data.get("production_version", data.get("storyboard_version", 1)),
        "quality_threshold": settings.animation_quality_threshold,
        "scenes": scenes,
        "controls": [
            "Regenerate Scene", "Regenerate Character", "Regenerate Background",
            "Change Expression", "Change Camera", "Change Animation", "Change Voice",
            "Change SFX", "Preview", "Edit",
        ],
    }


@router.patch("/{project_id}/scenes/{scene_id}")
def edit_production_scene(project_id: str, scene_id: int, req: SceneEditRequest):
    """Edit one scene without changing unrelated assets or audio."""
    output_dir = Path(settings.output_dir) / project_id
    changes = req.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No scene changes supplied")
    scene = _patch_scene_files(output_dir, scene_id, changes)
    _invalidate_render_outputs(output_dir, scene_id)
    return {"project_id": project_id, "scene": scene, "status": "updated"}


@router.post("/{project_id}/scenes/{scene_id}/preview")
def preview_production_scene(project_id: str, scene_id: int, quality: str = "PREVIEW"):
    """Render an actual animated scene preview with camera/effects/audio."""
    quality = quality.upper()
    if quality not in {"DRAFT", "PREVIEW", "FINAL"}:
        raise HTTPException(status_code=400, detail="quality must be DRAFT, PREVIEW, or FINAL")
    output_dir = Path(settings.output_dir) / project_id
    scene = _find_scene(output_dir, scene_id)
    from app.video.animated_renderer import Cinematic2DRenderer
    image = output_dir / "images" / f"scene_{scene_id:03d}.jpg"
    narration = output_dir / "audio" / "narration" / f"scene_{scene_id:03d}.mp3"
    preview = output_dir / "previews" / f"scene_{scene_id:03d}_{quality.lower()}.mp4"
    Cinematic2DRenderer(settings.video_width, settings.video_height, settings.video_fps).render_scene(
        scene,
        image if image.exists() else None,
        preview,
        narration_path=narration if narration.exists() else None,
        quality=quality,
    )
    return {"project_id": project_id, "scene_id": scene_id, "quality": quality, "preview_path": str(preview)}


@router.post("/{project_id}/scenes/{scene_id}/regenerate/{component}", status_code=202)
def regenerate_scene_component(
    project_id: str, scene_id: int, component: str,
    req: RegenerateComponentRequest,
):
    """Invalidate only the requested component, preserving all other work."""
    allowed = {"scene", "character", "background", "expression", "camera", "animation", "voice", "sfx"}
    component = component.lower()
    if component not in allowed:
        raise HTTPException(status_code=400, detail=f"component must be one of {sorted(allowed)}")
    output_dir = Path(settings.output_dir) / project_id
    changes = req.model_dump(exclude_none=True, exclude={"run_pipeline"})
    scene = _find_scene(output_dir, scene_id)
    if changes:
        scene = _patch_scene_files(output_dir, scene_id, changes)
    _invalidate_component(output_dir, scene_id, component)
    job_id = None
    if req.run_pipeline:
        from app.database.models import Project as ProjModel
        from app.database.session import get_session
        with get_session() as session:
            project = session.query(ProjModel).filter_by(id=project_id).first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            from app.api.job_runner import submit_pipeline_job
            job_id = submit_pipeline_job(
                project_id, project.topic, project.language or "English",
                project.target_duration_seconds or 480, project.style or "documentary",
                project.aspect_ratio or "16:9",
            )
    return {
        "project_id": project_id, "scene_id": scene_id, "component": component,
        "status": "queued" if job_id else "invalidated", "job_id": job_id,
        "preserved": sorted(allowed - {component, "scene"}),
    }


def _find_scene(output_dir: Path, scene_id: int) -> dict:
    for filename in ("production_plan.json", "storyboard.json"):
        path = output_dir / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for scene in data.get("scenes", []):
            if int(scene.get("scene_id", -1)) == scene_id:
                return scene
    raise HTTPException(status_code=404, detail="Scene not found")


def _patch_scene_files(output_dir: Path, scene_id: int, changes: dict) -> dict:
    from app.video.timeline import build_production_scene
    updated: dict | None = None
    for filename in ("storyboard.json", "production_plan.json"):
        path = output_dir / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for index, scene in enumerate(data.get("scenes", [])):
            if int(scene.get("scene_id", -1)) != scene_id:
                continue
            scene.update({k: v for k, v in changes.items() if k not in {"camera", "animation", "expression"}})
            for shot in scene.get("shots", []):
                if changes.get("camera"):
                    shot.setdefault("camera", {})["move"] = changes["camera"]
                if changes.get("animation"):
                    shot["action"] = changes["animation"]
                if changes.get("expression"):
                    shot["expression"] = changes["expression"]
            updated = build_production_scene(scene)
            data["scenes"][index] = updated
            break
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if updated is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    return updated


def _invalidate_render_outputs(output_dir: Path, scene_id: int) -> None:
    targets = [
        output_dir / "scenes" / f"scene_{scene_id:03d}.mp4",
        output_dir / "concat.mp4", output_dir / "subtitled.mp4",
        output_dir / "final.mp4", output_dir / "render_manifest.json",
    ]
    for path in targets:
        path.unlink(missing_ok=True)


def _invalidate_component(output_dir: Path, scene_id: int, component: str) -> None:
    if component in {"background", "scene"}:
        (output_dir / "images" / f"scene_{scene_id:03d}.jpg").unlink(missing_ok=True)
        _remove_manifest_key(output_dir / "images" / "manifest.json", scene_id)
    if component in {"voice", "scene"}:
        (output_dir / "audio" / "narration" / f"scene_{scene_id:03d}.mp3").unlink(missing_ok=True)
        _remove_manifest_key(output_dir / "audio" / "narration" / "manifest.json", scene_id)
    if component in {"character", "scene"}:
        # Character references remain intact; only derived puppet renders are invalidated.
        for path in (output_dir / "characters").glob("*.png") if (output_dir / "characters").exists() else []:
            path.unlink(missing_ok=True)
    _invalidate_render_outputs(output_dir, scene_id)


def _remove_manifest_key(path: Path, scene_id: int) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop(str(scene_id), None)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        path.unlink(missing_ok=True)


def _do_publish(project_id: str) -> dict:
    """Shared logic for approve and publish endpoints."""
    from app.database.models import YouTubeUpload
    from app.database.session import get_session
    from app.youtube.uploader import YouTubeUploader

    with get_session() as s:
        row = s.query(YouTubeUpload).filter_by(project_id=project_id).first()
        if not row or not row.video_id:
            raise HTTPException(
                status_code=404,
                detail="No YouTube upload found for this project. Run the pipeline with upload enabled first.",
            )
        video_id = row.video_id

    try:
        YouTubeUploader(project_id=project_id).publish(video_id)
        logger.info("video_published", project=project_id, video_id=video_id)
        return {
            "project_id": project_id,
            "video_id": video_id,
            "status": "published",
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{project_id}/approve")
def approve_project(project_id: str):
    """
    Human approval gate — publishes the private YouTube video to public.
    Must be called manually after reviewing the private video.
    """
    return _do_publish(project_id)


@router.post("/{project_id}/publish")
def publish_project(project_id: str):
    """
    Publish endpoint (spec-compliant alias for /approve).
    Moves a private/unlisted YouTube video to public after human review.
    """
    return _do_publish(project_id)
