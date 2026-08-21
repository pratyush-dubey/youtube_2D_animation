"""
app/api/routes.py — public façade that re-exports all routers.

The original spec referenced this file (app/api/routes.py) as the single
entry point for all API routes.  The actual route logic is split into:
  app/api/routes/projects.py
  app/api/routes/jobs.py

Import from here to keep external code stable even as internal organisation evolves.
"""
from app.api.routes.projects import router as projects_router
from app.api.routes.jobs import router as jobs_router

__all__ = ["projects_router", "jobs_router"]
