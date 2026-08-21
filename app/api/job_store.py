"""
Job store — single source of truth for background pipeline job state.

Uses a write-through strategy:
  - Fast in-memory dict for reads (no DB hit on every poll)
  - Every state change is immediately persisted to `pipeline_jobs` table
  - On startup the in-memory dict is reconstructed from the DB

This means jobs survive application restarts.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class JobStore:
    """Thread-safe, write-through job registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def create(self, job_id: str, project_id: str) -> dict[str, Any]:
        """Create a new job record (status=queued) and persist it."""
        job: dict[str, Any] = {
            "job_id": job_id,
            "project_id": project_id,
            "status": "queued",
            "stage": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
        }
        with self._lock:
            self._cache[job_id] = job
        self._persist(job)
        return job

    def update(self, job_id: str, **fields) -> None:
        """Update one or more fields of an existing job."""
        with self._lock:
            if job_id not in self._cache:
                return
            self._cache[job_id].update(fields)
            job = dict(self._cache[job_id])
        self._persist(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._cache[job_id]) if job_id in self._cache else None

    def get_latest_for_project(self, project_id: str) -> dict[str, Any] | None:
        """Return the most recently created job for a project."""
        with self._lock:
            matches = [
                j for j in self._cache.values()
                if j["project_id"] == project_id
            ]
        if not matches:
            return None
        return dict(sorted(matches, key=lambda j: j["started_at"] or "", reverse=True)[0])

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._cache.values())
        jobs.sort(key=lambda j: j.get("started_at") or "", reverse=True)
        return [dict(j) for j in jobs[:limit]]

    def load_from_db(self) -> None:
        """Populate in-memory cache from the database (called at startup)."""
        try:
            from app.database.models import PipelineJob
            from app.database.session import get_session
            with get_session() as s:
                rows = s.query(PipelineJob).order_by(PipelineJob.started_at).all()
                with self._lock:
                    for row in rows:
                        self._cache[row.job_id] = {
                            "job_id": row.job_id,
                            "project_id": row.project_id,
                            "status": row.status,
                            "stage": row.stage,
                            "started_at": str(row.started_at) if row.started_at else None,
                            "finished_at": str(row.finished_at) if row.finished_at else None,
                            "error": row.error_message,
                        }
            logger.info("job_store_loaded_from_db", count=len(self._cache))
        except Exception as exc:
            logger.warning("job_store_load_failed", error=str(exc))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _persist(self, job: dict[str, Any]) -> None:
        """Write-through: upsert job record to DB."""
        try:
            from app.database.models import PipelineJob
            from app.database.session import get_session

            def _parse_dt(value: str | None):
                if not value:
                    return None
                try:
                    return datetime.fromisoformat(value)
                except Exception:
                    return None

            with get_session() as s:
                row = s.query(PipelineJob).filter_by(job_id=job["job_id"]).first()
                if row is None:
                    row = PipelineJob(
                        job_id=job["job_id"],
                        project_id=job["project_id"],
                    )
                    s.add(row)
                row.status = job["status"]
                row.stage = job.get("stage")
                row.started_at = _parse_dt(job.get("started_at"))
                row.finished_at = _parse_dt(job.get("finished_at"))
                row.error_message = job.get("error")
        except Exception as exc:
            logger.warning("job_store_persist_failed", error=str(exc))


# Module-level singleton — import this from all other modules
job_store = JobStore()
