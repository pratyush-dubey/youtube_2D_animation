"""
Pipeline state machine.
Tracks per-project step completion so crashed pipelines can resume mid-way.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.database.models import PipelineStep, Project
from app.database.session import get_session

logger = structlog.get_logger(__name__)

# Canonical ordered list of pipeline stages
PIPELINE_STAGES = [
    "research",
    "script",
    "storyboard",
    "images",
    "voice",
    "music",
    "video",
    "quality",
    "metadata",
    "thumbnail",
    "upload",
]

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


class PipelineState:
    """
    Read/write pipeline state for a given project.

    Usage:
        state = PipelineState(project_id)
        if state.should_run("research"):
            # … do work …
            state.complete("research", output_data={...})
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._ensure_steps_exist()

    # ── public API ─────────────────────────────────────────────────────────

    def should_run(self, stage: str) -> bool:
        """Return True if the stage is not already marked complete."""
        status = self._get_status(stage)
        if status == STATUS_COMPLETE:
            logger.info("stage_skipped_already_complete", project=self.project_id, stage=stage)
            return False
        return True

    def start(self, stage: str) -> None:
        self._update_step(stage, STATUS_RUNNING, started_at=datetime.now(timezone.utc))
        logger.info("stage_started", project=self.project_id, stage=stage)

    def complete(self, stage: str, output_data: dict[str, Any] | None = None) -> None:
        self._update_step(
            stage,
            STATUS_COMPLETE,
            completed_at=datetime.now(timezone.utc),
            output_data=output_data,
        )
        logger.info("stage_complete", project=self.project_id, stage=stage)

    def fail(self, stage: str, error: str) -> None:
        self._update_step(
            stage,
            STATUS_FAILED,
            error_message=error,
            completed_at=datetime.now(timezone.utc),
        )
        logger.error("stage_failed", project=self.project_id, stage=stage, error=error)

    def increment_retry(self, stage: str) -> int:
        with get_session() as session:
            step = self._fetch_step(session, stage)
            step.retry_count = (step.retry_count or 0) + 1
            session.add(step)
            session.flush()
            new_count = step.retry_count
        return new_count

    def get_summary(self) -> dict[str, str]:
        with get_session() as session:
            steps = (
                session.query(PipelineStep)
                .filter_by(project_id=self.project_id)
                .all()
            )
            return {s.step_name: s.status for s in steps}

    def get_output(self, stage: str) -> dict[str, Any] | None:
        with get_session() as session:
            step = self._fetch_step(session, stage)
            return step.output_data

    # ── internal helpers ───────────────────────────────────────────────────

    def _ensure_steps_exist(self) -> None:
        """Insert pending rows for any missing stages (idempotent)."""
        with get_session() as session:
            existing = {
                s.step_name
                for s in session.query(PipelineStep)
                .filter_by(project_id=self.project_id)
                .all()
            }
            for stage in PIPELINE_STAGES:
                if stage not in existing:
                    session.add(
                        PipelineStep(
                            project_id=self.project_id,
                            step_name=stage,
                            status=STATUS_PENDING,
                        )
                    )

    def _fetch_step(self, session, stage: str) -> PipelineStep:
        step = (
            session.query(PipelineStep)
            .filter_by(project_id=self.project_id, step_name=stage)
            .first()
        )
        if step is None:
            raise ValueError(
                f"Pipeline step {stage!r} not found for project {self.project_id!r}"
            )
        return step

    def _get_status(self, stage: str) -> str:
        with get_session() as session:
            step = self._fetch_step(session, stage)
            return step.status

    def _update_step(self, stage: str, status: str, **kwargs) -> None:
        with get_session() as session:
            step = self._fetch_step(session, stage)
            step.status = status
            for k, v in kwargs.items():
                setattr(step, k, v)
            session.add(step)
