"""
Job runner — submits pipeline jobs to the background thread pool.

Separated from job_store so that routes, the scheduler, and the
CLI can all submit jobs through a single, consistent path.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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

        from app.agents.research_agent import ResearchAgent
        from app.agents.script_agent import ScriptAgent
        from app.agents.character_agent import CharacterAgent
        from app.agents.storyboard_agent import StoryboardAgent
        from app.agents.asset_agent import AssetAgent
        from app.agents.voice_agent import VoiceAgent
        from app.agents.music_agent import MusicAgent
        from app.agents.video_edit_agent import VideoEditAgent
        from app.agents.seo_agent import SEOAgent
        from app.agents.thumbnail_agent import ThumbnailAgent
        from app.agents.quality_agent import QualityAgent

        _step("research",   lambda: ResearchAgent(llm=llm).run(context))
        if context.research is None:
            raise RuntimeError("Research stage failed")

        _step("script",     lambda: ScriptAgent(llm=llm).run(context))
        if context.script is None:
            raise RuntimeError("Script stage failed")

        _step("characters", lambda: CharacterAgent(llm=llm).run(context))
        _step("storyboard", lambda: StoryboardAgent(llm=llm).run(context))
        _step("images",     lambda: AssetAgent().run(context))
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
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("pipeline_job_complete", job_id=job_id, project=project_id)

    except Exception as exc:
        job_store.update(
            job_id,
            status="failed",
            error=str(exc),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.error("pipeline_job_failed", job_id=job_id, project=project_id, error=str(exc))
