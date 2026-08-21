"""
ThumbnailAgent — wrapper agent around the thumbnail generator.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.llm.factory import get_llm_provider

logger = structlog.get_logger(__name__)


class ThumbnailAgent(Agent):
    name = "thumbnail_agent"
    max_retries = 1

    def __init__(self, llm=None) -> None:
        self.llm = llm or get_llm_provider()

    def _execute(self, context: AgentContext) -> Path:
        if context.seo is None:
            raise ValueError("SEOAgent must run before ThumbnailAgent")

        from app.thumbnail.generator import ThumbnailGenerator
        gen = ThumbnailGenerator(project_id=context.project_id, llm=self.llm)
        path = gen.generate(
            topic=context.chosen_topic or context.topic,
            seo=context.seo,
            output_dir=context.output_dir,
            style=context.style,
        )
        context.thumbnail_path = path
        logger.info("thumbnail_complete", project=context.project_id, path=str(path))
        return path
