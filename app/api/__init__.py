"""
app.api — FastAPI REST backend for the AI YouTube Automation system.

Public surface:
  create_app()          — FastAPI application factory
  projects_router       — /api/projects/* routes
  jobs_router           — /api/jobs/* routes
  submit_pipeline_job() — submit a background pipeline job
  job_store             — global job state store (in-memory + DB)
"""
from app.api.app import create_app, app
from app.api.routes import projects_router, jobs_router
from app.api.job_runner import submit_pipeline_job
from app.api.job_store import job_store

__all__ = [
    "create_app",
    "app",
    "projects_router",
    "jobs_router",
    "submit_pipeline_job",
    "job_store",
]
