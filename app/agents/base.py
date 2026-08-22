"""
Agent base class.

Every agent:
  - Receives an AgentContext (shared state for this video job)
  - Implements run() → returns its output, which is stored back into context
  - Logs structured events
  - Records LLM cost if it made API calls
  - Supports retry via the base class

An agent is intentionally thin — it delegates heavy lifting to
the existing service modules (LLM, DB, research, script, seo, etc.)
and only handles the glue logic for its step in the pipeline.
"""
from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from app.config.settings import settings

logger = structlog.get_logger(__name__)


@dataclass
class AgentContext:
    """
    Shared mutable state passed between all agents in a single video job.
    Each agent reads what it needs and writes its output back here.
    """
    # Job identity
    project_id: str
    topic: str
    language: str = "English"
    style: str = "documentary"
    target_duration_seconds: int = 480
    aspect_ratio: str = "16:9"

    # Output directory
    output_dir: Path = field(default_factory=lambda: Path("./output/unset"))

    # Stage outputs (populated as pipeline progresses)
    trending_topics: list[dict] = field(default_factory=list)
    chosen_topic: str = ""
    research: Any = None          # ResearchResult
    script: Any = None            # ScriptResult
    character_sheet: dict = field(default_factory=dict)  # key figures → visual description
    storyboard: Any = None        # list[SceneResult]
    images: dict[int, Path] = field(default_factory=dict)   # scene_id → Path
    narration_files: dict[int, Path] = field(default_factory=dict)
    audio_plan: dict = field(default_factory=dict)
    character_voice_map: dict = field(default_factory=dict)
    music_path: Path | None = None
    master_audio_path: Path | None = None
    video_path: Path | None = None
    thumbnail_path: Path | None = None
    seo: Any = None               # SEOMetadata
    youtube_video_id: str | None = None
    youtube_url: str | None = None

    # Cost / audit
    total_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    """Returned by every agent.run() call."""
    agent_name: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_seconds: float = 0.0
    cost_usd: float = 0.0


class Agent(ABC):
    """
    Abstract base for all pipeline agents.

    Subclasses implement _execute(context) → Any.
    The base class provides timing, retry, logging, and error capture.
    """
    name: str = "base_agent"
    max_retries: int = 2
    retry_delay: float = 3.0

    def run(self, context: AgentContext) -> AgentResult:
        log = logger.bind(agent=self.name, project=context.project_id)
        log.info("agent_started")
        t0 = time.monotonic()

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                output = self._execute(context)
                duration = round(time.monotonic() - t0, 2)
                log.info("agent_complete", duration_s=duration, attempt=attempt)
                return AgentResult(
                    agent_name=self.name,
                    success=True,
                    output=output,
                    duration_seconds=duration,
                )
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "agent_attempt_failed",
                    attempt=attempt,
                    max=self.max_retries + 1,
                    error=str(exc)[:200],
                )
                if attempt <= self.max_retries:
                    time.sleep(self.retry_delay * attempt)

        duration = round(time.monotonic() - t0, 2)
        err = f"{type(last_exc).__name__}: {str(last_exc)[:300]}"
        tb_str = traceback.format_exc()[-400:]
        log.error("agent_failed", error=err, traceback=tb_str)
        context.errors.append(f"[{self.name}] {err}")
        return AgentResult(
            agent_name=self.name,
            success=False,
            error=err,
            duration_seconds=duration,
        )

    @abstractmethod
    def _execute(self, context: AgentContext) -> Any:
        """Agent-specific logic. Return the stage output."""
        ...
