"""
SQLAlchemy 2.x ORM models.
Uses SQLite by default; same models work against PostgreSQL by changing the engine URL.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


class Base(DeclarativeBase):
    pass


# ── Projects ───────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="English")
    style: Mapped[str] = mapped_column(String(50), default="documentary")
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=480)
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="16:9")
    status: Mapped[str] = mapped_column(String(30), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    # relationships
    pipeline_steps: Mapped[list[PipelineStep]] = relationship(back_populates="project", cascade="all, delete-orphan")
    research: Mapped[Research | None] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    sources: Mapped[list[Source]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scripts: Mapped[list[Script]] = relationship(back_populates="project", cascade="all, delete-orphan")
    videos: Mapped[list[Video]] = relationship(back_populates="project", cascade="all, delete-orphan")
    metadata_: Mapped[Metadata | None] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    youtube_upload: Mapped[YouTubeUpload | None] = relationship(back_populates="project", uselist=False, cascade="all, delete-orphan")
    api_costs: Mapped[list[ApiCost]] = relationship(back_populates="project", cascade="all, delete-orphan")
    logs: Mapped[list[PipelineLog]] = relationship(back_populates="project", cascade="all, delete-orphan")
    pipeline_jobs: Mapped[list["PipelineJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")


# ── Pipeline Steps ─────────────────────────────────────────────────────────────

class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | running | complete | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    output_data: Mapped[dict | None] = mapped_column(JSON)

    project: Mapped[Project] = relationship(back_populates="pipeline_steps")


# ── Research ───────────────────────────────────────────────────────────────────

class Research(Base):
    __tablename__ = "research"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, unique=True)
    facts: Mapped[list | None] = mapped_column(JSON)
    claims: Mapped[list | None] = mapped_column(JSON)
    statistics: Mapped[list | None] = mapped_column(JSON)
    locations: Mapped[list | None] = mapped_column(JSON)
    people: Mapped[list | None] = mapped_column(JSON)
    uncertain_claims: Mapped[list | None] = mapped_column(JSON)
    dates: Mapped[list | None] = mapped_column(JSON)
    raw_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="research")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    accessed_at: Mapped[str | None] = mapped_column(String(30))
    credibility_score: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="sources")


# ── Script / Scenes ────────────────────────────────────────────────────────────

class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    hook: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(Text)
    call_to_action: Mapped[str | None] = mapped_column(Text)
    estimated_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="scripts")
    scenes: Mapped[list[Scene]] = relationship(back_populates="script", cascade="all, delete-orphan", order_by="Scene.scene_order")


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id"), nullable=False)
    scene_order: Mapped[int] = mapped_column(Integer, nullable=False)
    narration: Mapped[str | None] = mapped_column(Text)
    visual_description: Mapped[str | None] = mapped_column(Text)
    image_prompt: Mapped[str | None] = mapped_column(Text)
    animation_type: Mapped[str | None] = mapped_column(String(50))
    camera_motion: Mapped[str | None] = mapped_column(String(50))
    text_overlay: Mapped[str | None] = mapped_column(Text)
    transition_type: Mapped[str | None] = mapped_column(String(50))
    music_mood: Mapped[str | None] = mapped_column(String(50))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    sfx_list: Mapped[list | None] = mapped_column(JSON)
    shot_plan: Mapped[list | None] = mapped_column(JSON)
    layer_graph: Mapped[list | None] = mapped_column(JSON)
    animation_timeline: Mapped[dict | None] = mapped_column(JSON)
    animation_quality: Mapped[dict | None] = mapped_column(JSON)
    render_mode: Mapped[str | None] = mapped_column(String(40))
    random_seed: Mapped[int | None] = mapped_column(Integer)

    script: Mapped[Script] = relationship(back_populates="scenes")
    assets: Mapped[list[Asset]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    audio_files: Mapped[list[AudioFile]] = relationship(back_populates="scene", cascade="all, delete-orphan")


# ── Assets ─────────────────────────────────────────────────────────────────────

class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(30))  # image | video | overlay
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50))
    license: Mapped[str | None] = mapped_column(String(100))
    license_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    commercial_use: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    scene: Mapped[Scene] = relationship(back_populates="assets")


class AudioFile(Base):
    __tablename__ = "audio_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id"), nullable=False)
    audio_type: Mapped[str] = mapped_column(String(30))  # narration | sfx | music
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    scene: Mapped[Scene] = relationship(back_populates="audio_files")


# ── Video ──────────────────────────────────────────────────────────────────────

class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    quality_passed: Mapped[bool | None] = mapped_column(Boolean)
    quality_report: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="videos")


# ── Metadata / SEO ────────────────────────────────────────────────────────────

class Metadata(Base):
    __tablename__ = "metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    hashtags: Mapped[list | None] = mapped_column(JSON)
    chapters: Mapped[list | None] = mapped_column(JSON)
    title_score: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="metadata_")


# ── YouTube Upload ─────────────────────────────────────────────────────────────

class YouTubeUpload(Base):
    __tablename__ = "youtube_uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, unique=True)
    video_id: Mapped[str | None] = mapped_column(String(20))
    url: Mapped[str | None] = mapped_column(Text)
    privacy_status: Mapped[str] = mapped_column(String(20), default="private")
    thumbnail_uploaded: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)

    project: Mapped[Project] = relationship(back_populates="youtube_upload")


# ── Cost Tracking ──────────────────────────────────────────────────────────────

class ApiCost(Base):
    __tablename__ = "api_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    operation: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="api_costs")


# ── Pipeline Logs ──────────────────────────────────────────────────────────────

class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    stage: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="logs")


# ── Pipeline Jobs (background API jobs) ───────────────────────────────────────

class PipelineJob(Base):
    """
    Persists background pipeline job state so jobs survive application restarts.
    One row per job submitted via the REST API or the scheduler.
    """
    __tablename__ = "pipeline_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")   # queued|running|complete|failed
    stage: Mapped[str | None] = mapped_column(String(50))               # current agent name
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="pipeline_jobs")
