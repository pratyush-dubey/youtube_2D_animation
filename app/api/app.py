"""
FastAPI application factory.

All route logic lives in:
  app/api/routes/projects.py  — /api/projects/*
  app/api/routes/jobs.py      — /api/jobs/*

This module's sole responsibilities:
  1. Create and configure the FastAPI app instance
  2. Register middleware
  3. Include the routers under /api
  4. Manage lifespan (DB init, scheduler start, job-store warm-up)
"""
from __future__ import annotations

import contextlib

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.database.session import init_db

logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # ── startup ──────────────────────────────────────────────────────
        init_db()

        # Warm up the job store from the DB so in-flight jobs from a
        # previous process are visible immediately after restart.
        from app.api.job_store import job_store
        job_store.load_from_db()

        if settings.scheduler_enabled:
            try:
                from app.scheduler.job_scheduler import VideoScheduler
                sched = VideoScheduler()
                sched.start()
                app.state.scheduler = sched
                logger.info("scheduler_auto_started", niche=settings.scheduler_niche)
            except Exception as exc:
                logger.warning("scheduler_start_failed", error=str(exc))

        yield

        # ── shutdown ─────────────────────────────────────────────────────
        if hasattr(app.state, "scheduler"):
            app.state.scheduler.stop()

    app = FastAPI(
        title="AI YouTube Automation API",
        description=(
            "Automated 2D YouTube video generation: "
            "topic → research → script → storyboard → video → YouTube upload"
        ),
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Root health (not under /api so load-balancer probes work without the prefix)
    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok", "version": settings.app_version}

    # Register routers under /api
    from app.api.routes import projects_router, jobs_router
    app.include_router(projects_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")

    return app


# Module-level app instance used by uvicorn / gunicorn
app = create_app()
