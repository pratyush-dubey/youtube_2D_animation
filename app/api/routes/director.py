"""Default one-request/one-button AI Video Director API."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.director.director import Director, VideoRequest

router = APIRouter(prefix="/director", tags=["ai-video-director"])


class CreateVideoRequest(BaseModel):
    request: str = Field(..., min_length=10, max_length=2000)
    duration_seconds: int = Field(60, ge=30, le=3600)
    language: str = Field("English", min_length=2, max_length=40)
    style: str = Field("Cinematic Documentary", min_length=2, max_length=80)


class ChangeRequest(BaseModel):
    request: str = Field(..., min_length=3, max_length=1000)


class ApprovalRequest(BaseModel):
    schedule_at: str | None = None


def _project(project_id: str):
    from app.database.models import Project
    from app.database.session import get_session
    with get_session() as session:
        row = session.query(Project).filter_by(id=project_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return {
            "project_id": row.id, "request": row.topic, "language": row.language,
            "style": row.style, "duration_seconds": row.target_duration_seconds,
            "state": row.status.upper(), "created_at": str(row.created_at),
        }


def _artifacts(project_id: str) -> dict:
    root = Path(settings.output_dir) / project_id
    seo = {}
    quality = {}
    for filename, target in (("seo.json", seo), ("quality_report.json", quality)):
        try:
            target.update(json.loads((root / filename).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    from app.metadata.sanitizer import sanitize_metadata_payload
    seo = sanitize_metadata_payload(seo)
    return {
        "video": f"/api/projects/{project_id}/media?path=final.mp4" if (root / "final.mp4").is_file() else None,
        "thumbnail": f"/api/projects/{project_id}/media?path=thumbnail.jpg" if (root / "thumbnail.jpg").is_file() else None,
        "subtitles_srt": f"/api/projects/{project_id}/media?path=subtitles.srt" if (root / "subtitles.srt").is_file() else None,
        "subtitles_vtt": f"/api/projects/{project_id}/media?path=subtitles.vtt" if (root / "subtitles.vtt").is_file() else None,
        "title": seo.get("best_title"), "description": seo.get("description"),
        "tags": seo.get("tags", []), "chapters": seo.get("chapters", []),
        "quality_score": quality.get("score"), "quality": quality,
    }


@router.post("/videos", status_code=202)
def create_video(req: CreateVideoRequest):
    """Create a project and immediately run its complete production graph."""
    from app.api.job_runner import submit_director_job
    from app.database.models import Project
    from app.database.session import get_session

    parsed = VideoRequest.from_natural_language(
        req.request, req.duration_seconds, req.language, req.style,
    )
    project_id = str(uuid.uuid4())[:8]
    with get_session() as session:
        session.add(Project(
            id=project_id, topic=parsed.request, language=parsed.language,
            style=parsed.style, target_duration_seconds=parsed.duration_seconds,
            aspect_ratio=parsed.aspect_ratio, status="queued",
        ))
    job_id = submit_director_job(project_id, parsed)
    return {"project_id": project_id, "job_id": job_id, "state": "QUEUED", "url": f"/projects/{project_id}"}


@router.get("/projects/{project_id}")
def get_director_project(project_id: str):
    project = _project(project_id)
    state = Director.read_state(project_id)
    if state:
        project.update(state)
    else:
        # Provider/bootstrap failures can happen before the graph state exists.
        # Surface the persisted job terminal state so the UI never polls forever.
        from app.api.job_store import job_store

        job = job_store.get_latest_for_project(project_id)
        if job and job.get("status") in {"failed", "requires_attention"}:
            project.update({
                "state": "REQUIRES_ATTENTION",
                "requires_attention": True,
                "progress": job.get("progress", 0),
                "message": job.get("error") or "Production needs attention.",
            })
    project["artifacts"] = _artifacts(project_id)
    return project


@router.post("/projects/{project_id}/changes", status_code=202)
def request_changes(project_id: str, req: ChangeRequest):
    """Route plain-language feedback to the affected subsystem and rerun caches."""
    project = _project(project_id)
    text = req.request.lower()
    target = "visuals"
    if any(word in text for word in ("narrat", "voice", "dramatic", "pronounc")):
        target = "voice"
    elif any(word in text for word in ("thumbnail", "cover")):
        target = "thumbnail"
    elif any(word in text for word in ("music", "sound", "sfx", "audio")):
        target = "sound"
    elif any(word in text for word in ("script", "story", "fact", "wording")):
        target = "script"
    elif any(word in text for word in ("character", "face", "looks wrong", "hands")):
        target = "characters"

    root = Path(settings.output_dir) / project_id
    invalidations = {
        "voice": ["audio", "final.mp4", "subtitled.mp4", "quality_report.json"],
        "thumbnail": ["thumbnail.jpg", "quality_report.json"],
        "sound": ["audio", "music.mp3", "final.mp4", "quality_report.json"],
        "script": ["script.json", "storyboard.json", "production_plan.json", "final.mp4", "quality_report.json"],
        "characters": ["characters.json", "images", "final.mp4", "quality_report.json"],
        "visuals": ["storyboard.json", "images", "final.mp4", "quality_report.json"],
    }
    # Move only generated cache files out of the next run's way; retain history in revision metadata.
    for relative in invalidations[target]:
        path = root / relative
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            # Do not recursively delete user data; agents overwrite/rebuild their manifests.
            for child in path.glob("manifest.json"):
                child.unlink(missing_ok=True)

    revision_path = root / "revisions.json"
    try:
        revisions = json.loads(revision_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        revisions = []
    revisions.append({"request": req.request, "target": target})
    revision_path.write_text(json.dumps(revisions, indent=2), encoding="utf-8")

    from app.api.job_runner import submit_director_job
    video_request = VideoRequest(project["request"], project["duration_seconds"], project["language"], project["style"])
    job_id = submit_director_job(project_id, video_request)
    return {"project_id": project_id, "job_id": job_id, "state": "QUEUED", "routed_to": target}


@router.post("/projects/{project_id}/stages/{stage}/retry", status_code=202)
def retry_failed_stage(project_id: str, stage: str):
    """Retry exactly one failed graph stage, then continue pending dependents."""
    project = _project(project_id)
    state = Director.read_state(project_id)
    if not state or stage not in state.get("stages", {}):
        raise HTTPException(status_code=404, detail="Production stage not found")
    if state["stages"][stage].get("status") != "failed":
        raise HTTPException(status_code=409, detail="Only a failed stage can be retried")

    from app.api.job_store import job_store
    active = job_store.get_latest_for_project(project_id)
    if active and active.get("status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="A production job is already running")

    from app.api.job_runner import submit_director_stage_retry
    video_request = VideoRequest(
        project["request"], project["duration_seconds"],
        project["language"], project["style"],
    )
    job_id = submit_director_stage_retry(project_id, video_request, stage)
    return {
        "project_id": project_id, "job_id": job_id,
        "state": "QUEUED", "retrying_stage": stage,
        "preserved_stages": [
            name for name, item in state["stages"].items()
            if item.get("status") == "complete"
        ],
    }


@router.post("/projects/{project_id}/diagnostics/comfyui")
def test_comfyui(project_id: str):
    """Advanced-mode health/model/workflow check; does not generate an image."""
    _project(project_id)
    from app.image_generation.comfyui_client import ComfyUIClient

    client = ComfyUIClient(settings.comfyui_base_url, timeout=15)
    health = client.health()
    client.validate_checkpoint("DreamShaper_8_pruned.safetensors")
    workflow = json.loads(Path(settings.comfyui_scene_workflow).read_text(encoding="utf-8"))
    client.validate_workflow(workflow)
    return {"status": "PASS", "health": True, "checkpoint": True, "workflow": True, "system": health.get("system", {})}


@router.post("/projects/{project_id}/diagnostics/visual", status_code=202)
def test_visual_generation(project_id: str):
    """Queue exactly one isolated 512x768 image; never block this request."""
    _project(project_id)
    from app.api.job_runner import submit_visual_diagnostic_job

    job_id = submit_visual_diagnostic_job(project_id)
    return {"status": "QUEUED", "job_id": job_id, "poll": f"/api/jobs/{job_id}"}


@router.post("/projects/{project_id}/approve", status_code=202)
def approve_and_schedule(project_id: str, req: ApprovalRequest):
    """Authoritative human gate. Never publish a failed or unreviewed video."""
    project = get_director_project(project_id)
    state = str(project.get("state", "")).upper()
    score = project.get("artifacts", {}).get("quality_score")
    if state != "VIDEO_READY" or score is None or score < settings.minimum_video_quality_score:
        raise HTTPException(status_code=409, detail="Publishing is blocked until production and quality control pass")
    from app.database.models import Project
    from app.database.session import get_session
    from app.director.scheduling import next_publish_slot
    schedule_at = req.schedule_at or next_publish_slot()
    with get_session() as session:
        row = session.query(Project).filter_by(id=project_id).first()
        row.status = "approved"
    approval_path = Path(settings.output_dir) / project_id / "approval.json"
    approval_path.write_text(json.dumps({"approved": True, "schedule_at": schedule_at}, indent=2), encoding="utf-8")
    director_state_path = Path(settings.output_dir) / project_id / Director.state_filename
    try:
        director_state = json.loads(director_state_path.read_text(encoding="utf-8"))
        director_state["state"] = "APPROVED"
        director_state["schedule_at"] = schedule_at
        director_state["stages"]["youtube"].update(
            status="queued" if settings.youtube_client_id else "waiting_credentials",
            message=None if settings.youtube_client_id else "Add YouTube credentials to schedule automatically",
        )
        director_state_path.write_text(json.dumps(director_state, indent=2), encoding="utf-8")
    except (OSError, ValueError, KeyError):
        pass
    youtube_job_id = None
    if settings.youtube_client_id and settings.youtube_client_secret:
        from app.api.job_runner import submit_youtube_schedule_job
        youtube_job_id = submit_youtube_schedule_job(project_id, schedule_at)
    return {
        "project_id": project_id, "state": "APPROVED",
        "schedule_at": schedule_at, "job_id": youtube_job_id,
        "youtube": "upload_queued" if youtube_job_id else "credentials_required",
        "message": (
            "Approval recorded and YouTube scheduling queued."
            if youtube_job_id else
            "Approval recorded. Add YouTube credentials to enable automatic upload and scheduling."
        ),
    }
