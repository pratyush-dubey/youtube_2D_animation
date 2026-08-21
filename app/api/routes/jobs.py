"""
Jobs router — background job status.

Routes (all under /api prefix added in app factory):
  GET /jobs       — list all jobs (most recent first)
  GET /jobs/{id}  — single job status
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(limit: int = 50):
    """List all background pipeline jobs, most recent first."""
    from app.api.job_store import job_store
    return job_store.list_jobs(limit=limit)


@router.get("/{job_id}")
def get_job(job_id: str):
    """Get the status of a single background job."""
    from app.api.job_store import job_store
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
