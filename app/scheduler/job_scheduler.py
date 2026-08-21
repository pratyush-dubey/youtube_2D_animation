"""
VideoScheduler — APScheduler-based autonomous video production cron job.

When `SCHEDULER_ENABLED=true` the scheduler fires every
`SCHEDULER_INTERVAL_DAYS` days (default 3) and:

  1. Runs TrendAgent to find a trending topic in the configured niche
  2. Runs the full agent pipeline (research → script → storyboard → assets →
     voice → music → video → quality → SEO → thumbnail → YouTube upload)
  3. Always uploads as PRIVATE — human approval required to publish

The scheduler can be started:
  - From the CLI:   python -m app.main scheduler start
  - Programmatically:  VideoScheduler().start()
  - Via FastAPI startup event

State persistence:
  Each scheduled job creates a Project row in the database with a unique
  project_id so the full pipeline state is resumable if the process restarts.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import settings

logger = structlog.get_logger(__name__)


class VideoScheduler:
    """
    Wraps APScheduler to run the full agent pipeline on an interval.

    Usage:
        scheduler = VideoScheduler(niche="science")
        scheduler.start()          # non-blocking background thread
        # … app runs …
        scheduler.stop()
    """

    def __init__(
        self,
        niche: str | None = None,
        interval_days: int | None = None,
        llm_provider_override: str | None = None,
    ) -> None:
        from app.scheduler.niche_config import get_niche_config
        self.niche_name = niche or settings.scheduler_niche
        self.niche_config = get_niche_config(self.niche_name)
        self.interval_days = interval_days or settings.scheduler_interval_days
        self.llm_override = llm_provider_override
        self._scheduler = None
        self._lock = threading.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self, run_immediately: bool = False) -> None:
        """
        Start the background scheduler.

        Args:
            run_immediately: If True, run one job immediately before scheduling.
        """
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger
        except ImportError:
            logger.error(
                "apscheduler_not_installed",
                hint="pip install apscheduler>=3.10",
            )
            raise

        with self._lock:
            if self._scheduler is not None and self._scheduler.running:
                logger.warning("scheduler_already_running")
                return

            self._scheduler = BackgroundScheduler(
                job_defaults={"coalesce": True, "max_instances": 1},
                timezone="UTC",
            )
            self._scheduler.add_job(
                func=self._run_job,
                trigger=IntervalTrigger(days=self.interval_days),
                id="video_generation",
                name=f"Video generation — {self.niche_name}",
                replace_existing=True,
            )
            self._scheduler.start()

            logger.info(
                "scheduler_started",
                niche=self.niche_name,
                interval_days=self.interval_days,
            )

        if run_immediately:
            logger.info("scheduler_running_immediate_job")
            self._run_job()

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        with self._lock:
            if self._scheduler and self._scheduler.running:
                self._scheduler.shutdown(wait=True)
                logger.info("scheduler_stopped")

    def trigger_now(self) -> str:
        """
        Manually trigger a job immediately (outside the regular schedule).
        Returns the project_id of the created job.
        """
        return self._run_job()

    # ── Job implementation ─────────────────────────────────────────────────

    def _run_job(self) -> str:
        """
        Core job: pick a topic, run the full pipeline, upload to YouTube.
        Returns the project_id.
        """
        project_id = str(uuid.uuid4())[:8]
        log = logger.bind(project=project_id, niche=self.niche_name)
        log.info("scheduled_job_started", timestamp=datetime.now(timezone.utc).isoformat())

        try:
            from app.agents.base import AgentContext
            from pathlib import Path
            output_dir = Path(settings.output_dir) / project_id
            output_dir.mkdir(parents=True, exist_ok=True)
    
            context = AgentContext(
                project_id=project_id,
                topic=self.niche_config.niche,    # will be overwritten by TrendAgent
                language=self.niche_config.language,
                style=self.niche_config.style,
                target_duration_seconds=self.niche_config.target_duration_seconds,
                aspect_ratio=self.niche_config.aspect_ratio,
                output_dir=output_dir,
            )
    
            # Insert Project row so FK constraints on api_costs etc. are satisfied
            from app.database.models import Project
            from app.database.session import get_session
            with get_session() as s:
                s.add(Project(
                    id=project_id,
                    topic=self.niche_config.niche,
                    language=self.niche_config.language,
                    target_duration_seconds=self.niche_config.target_duration_seconds,
                    style=self.niche_config.style,
                    aspect_ratio=self.niche_config.aspect_ratio,
                    status="created",
                ))

            self._run_pipeline(context, log)

            log.info(
                "scheduled_job_complete",
                topic=context.chosen_topic or context.topic,
                youtube_url=context.youtube_url,
            )
            return project_id

        except Exception as exc:
            log.error("scheduled_job_failed", error=str(exc), exc_info=True)
            return project_id

    def _run_pipeline(self, context, log) -> None:
        """Execute the full 13-agent pipeline for the given context."""
        from app.llm.factory import get_llm_provider
        from app.database.session import init_db

        init_db()
        llm = get_llm_provider(self.llm_override)

        # ── 1. Trend detection ──────────────────────────────────────────
        from app.agents.trend_agent import TrendAgent
        trend_result = TrendAgent(niche=self.niche_name, llm=llm).run(context)
        if trend_result.success and context.trending_topics:
            context.chosen_topic = context.trending_topics[0]["topic"]
            context.topic = context.chosen_topic
            log.info("topic_chosen", topic=context.chosen_topic)

        # ── 2. Research ─────────────────────────────────────────────────
        from app.agents.research_agent import ResearchAgent
        r = ResearchAgent(llm=llm).run(context)
        if not r.success:
            log.warning("research_failed", error=r.error)

        # ── 3. Script ───────────────────────────────────────────────────
        if context.research is None:
            log.error("pipeline_aborted", reason="research_failed")
            return
        from app.agents.script_agent import ScriptAgent
        s = ScriptAgent(llm=llm).run(context)
        if not s.success:
            log.error("pipeline_aborted", reason="script_failed")
            return

        # ── 4. Storyboard ───────────────────────────────────────────────
        from app.agents.storyboard_agent import StoryboardAgent
        StoryboardAgent(llm=llm).run(context)

        # ── 5. Images ───────────────────────────────────────────────────
        from app.agents.asset_agent import AssetAgent
        AssetAgent().run(context)

        # ── 6. Voice ────────────────────────────────────────────────────
        from app.agents.voice_agent import VoiceAgent
        VoiceAgent().run(context)

        # ── 7. Music ────────────────────────────────────────────────────
        from app.agents.music_agent import MusicAgent
        MusicAgent().run(context)

        # ── 8. Video editing ────────────────────────────────────────────
        from app.agents.video_edit_agent import VideoEditAgent
        v = VideoEditAgent().run(context)
        if not v.success:
            log.warning("video_edit_failed", error=v.error)

        # ── 9. SEO metadata ─────────────────────────────────────────────
        from app.agents.seo_agent import SEOAgent
        SEOAgent(llm=llm).run(context)

        # ── 10. Thumbnail ───────────────────────────────────────────────
        from app.agents.thumbnail_agent import ThumbnailAgent
        ThumbnailAgent(llm=llm).run(context)

        # ── 11. Quality check ───────────────────────────────────────────
        from app.agents.quality_agent import QualityAgent
        qr = QualityAgent().run(context)
        if qr.success and qr.output and not qr.output.passed:
            failed_checks = [c["check"] for c in qr.output.checks if not c["passed"]]
            log.warning("quality_check_failed", failed=failed_checks)

        # ── 12. YouTube upload ──────────────────────────────────────────
        if (
            self.niche_config.upload_after_render
            and context.video_path
            and context.video_path.exists()
            and settings.youtube_client_id
        ):
            from app.agents.youtube_agent import YouTubeAgent
            yt = YouTubeAgent().run(context)
            if not yt.success:
                log.warning("youtube_upload_failed", error=yt.error)
        else:
            log.info(
                "youtube_upload_skipped",
                reason=(
                    "upload_after_render disabled"
                    if not self.niche_config.upload_after_render
                    else "no video file or YouTube credentials not configured"
                ),
            )

    # ── Status ─────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return bool(self._scheduler and self._scheduler.running)

    def next_run_time(self) -> datetime | None:
        if not self._scheduler:
            return None
        job = self._scheduler.get_job("video_generation")
        return job.next_run_time if job else None
