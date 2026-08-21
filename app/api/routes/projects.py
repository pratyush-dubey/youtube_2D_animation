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
