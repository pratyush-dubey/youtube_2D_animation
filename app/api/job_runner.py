"""
Job runner — submits pipeline jobs to the background thread pool.

Separated from job_store so that routes, the scheduler, and the
CLI can all submit jobs through a single, consistent path.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.config.settings import settings

logger = structlog.get_logger(__name__)

# Global thread pool (max 2 concurrent pipeline jobs)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline")


def submit_pipeline_job(
    project_id: str,
    topic: str,
    language: str,
    duration: int,
    style: str,
    aspect_ratio: str,
) -> str:
    """Create a job record, submit it to the thread pool, return job_id."""
    from app.api.job_store import job_store

    job_id = str(uuid.uuid4())[:12]
    job_store.create(job_id, project_id)

    _executor.submit(
        _run_pipeline_job,
        job_id, project_id, topic, language, duration, style, aspect_ratio,
    )
    logger.info("pipeline_job_submitted", job_id=job_id, project=project_id)
    return job_id


def submit_director_job(project_id: str, video_request) -> str:
    """Submit the product-level one-click Director pipeline."""
    from app.api.job_store import job_store

    job_id = str(uuid.uuid4())[:12]
    job_store.create(job_id, project_id)
    _executor.submit(_run_director_job, job_id, project_id, video_request)
    logger.info("director_job_submitted", job_id=job_id, project=project_id)
    return job_id


def _run_director_job(job_id: str, project_id: str, video_request) -> None:
    from app.api.job_store import job_store
    from app.director.director import Director

    job_store.update(job_id, status="running", production_state="PRODUCING", progress=0)
    try:
        Director(job_id, project_id, video_request).execute()
    except Exception as exc:  # defensive: Director normally converts failures to safe state
        from app.database.models import Project
        from app.database.session import get_session

        with get_session() as session:
            project = session.query(Project).filter_by(id=project_id).first()
            if project:
                project.status = "requires_attention"
        job_store.update(
            job_id, status="requires_attention",
            error="Production could not be completed automatically.",
            finished_at=datetime.now(UTC).isoformat(),
        )
        logger.exception("director_job_crashed", job_id=job_id, project=project_id, error=str(exc))


def submit_youtube_schedule_job(project_id: str, schedule_at: str) -> str:
    """Upload and schedule a QA-approved project without blocking the UI."""
    from app.api.job_store import job_store

    job_id = str(uuid.uuid4())[:12]
    job_store.create(job_id, project_id)
    _executor.submit(_run_youtube_schedule_job, job_id, project_id, schedule_at)
    return job_id


def _run_youtube_schedule_job(job_id: str, project_id: str, schedule_at: str) -> None:
    import json

    from app.api.job_store import job_store
    from app.seo.schemas import SEOMetadata
    from app.youtube.uploader import YouTubeUploader

    job_store.update(job_id, status="running", stage="youtube", progress=10)
    root = Path(settings.output_dir) / project_id
    try:
        metadata = SEOMetadata.model_validate_json((root / "seo.json").read_text(encoding="utf-8"))
        uploader = YouTubeUploader(project_id)
        uploaded = uploader.upload(
            root / "final.mp4", metadata,
            root / "thumbnail.jpg" if (root / "thumbnail.jpg").is_file() else None,
            privacy_status="private",
        )
        uploader.schedule(uploaded.video_id, schedule_at)
        state_path = root / "director_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["state"] = "SCHEDULED"
        state["youtube"] = {**uploaded.to_dict(), "schedule_at": schedule_at}
        state["stages"]["youtube"].update(status="complete", progress=100, message=None)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        job_store.update(job_id, status="complete", stage=None, progress=100, finished_at=datetime.now(UTC).isoformat())
    except Exception as exc:
        job_store.update(
            job_id, status="requires_attention", stage="youtube",
            error="YouTube scheduling needs attention.",
            finished_at=datetime.now(UTC).isoformat(),
        )
        logger.exception("youtube_schedule_failed", project=project_id, error=str(exc))


def _run_pipeline_job(
    job_id: str,
    project_id: str,
    topic: str,
    language: str,
    duration: int,
    style: str,
    aspect_ratio: str,
) -> None:
    """Runs in a background thread — executes the full 13-agent pipeline."""
    from app.api.job_store import job_store

    job_store.update(job_id, status="running")

    try:
        from app.agents.base import AgentContext
        from app.llm.factory import get_llm_provider

        output_dir = Path(settings.output_dir) / project_id
        output_dir.mkdir(parents=True, exist_ok=True)

        llm = get_llm_provider()
        context = AgentContext(
            project_id=project_id,
            topic=topic,
            language=language,
            style=style,
            target_duration_seconds=duration,
            aspect_ratio=aspect_ratio,
            output_dir=output_dir,
        )

        def _step(agent_name: str, agent_fn):
            job_store.update(job_id, stage=agent_name)
            return agent_fn()

        from app.agents.asset_agent import AssetAgent
        from app.agents.audio_director_agent import AudioDirectorAgent
        from app.agents.character_agent import CharacterAgent
        from app.agents.music_agent import MusicAgent
        from app.agents.quality_agent import QualityAgent
        from app.agents.research_agent import ResearchAgent
        from app.agents.script_agent import ScriptAgent
        from app.agents.seo_agent import SEOAgent
        from app.agents.storyboard_agent import StoryboardAgent
        from app.agents.thumbnail_agent import ThumbnailAgent
        from app.agents.video_edit_agent import VideoEditAgent
        from app.agents.voice_agent import VoiceAgent

        _step("research",   lambda: ResearchAgent(llm=llm).run(context))
        if context.research is None:
            raise RuntimeError("Research stage failed")

        _step("script",     lambda: ScriptAgent(llm=llm).run(context))
        if context.script is None:
            raise RuntimeError("Script stage failed")

        _step("characters", lambda: CharacterAgent(llm=llm).run(context))
        _step("storyboard", lambda: StoryboardAgent(llm=llm).run(context))
        _step("images",     lambda: AssetAgent().run(context))
        _step("audio_direction", lambda: AudioDirectorAgent().run(context))
        _step("voice",      lambda: VoiceAgent().run(context))
        _step("music",      lambda: MusicAgent().run(context))
        _step("video",      lambda: VideoEditAgent().run(context))
        _step("seo",        lambda: SEOAgent(llm=llm).run(context))
        _step("thumbnail",  lambda: ThumbnailAgent(llm=llm).run(context))
        quality = _step("quality", lambda: QualityAgent().run(context))
        if not quality.success or not quality.output or not quality.output.passed:
            failed = [
                check["check"] for check in getattr(quality.output, "checks", [])
                if not check["passed"]
            ]
            raise RuntimeError(f"Quality gate failed: {', '.join(failed) or quality.error}")

        if (
            context.video_path
            and context.video_path.exists()
            and settings.youtube_client_id
        ):
            from app.agents.youtube_agent import YouTubeAgent
            _step("upload", lambda: YouTubeAgent().run(context))

        job_store.update(
            job_id,
            status="complete",
            stage=None,
            finished_at=datetime.now(UTC).isoformat(),
        )
        logger.info("pipeline_job_complete", job_id=job_id, project=project_id)

    except Exception as exc:
        job_store.update(
            job_id,
            status="failed",
            error=str(exc),
            finished_at=datetime.now(UTC).isoformat(),
        )
        logger.error("pipeline_job_failed", job_id=job_id, project=project_id, error=str(exc))
