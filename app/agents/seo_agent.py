"""
SEOAgent — wrapper agent around the SEO metadata generator.
"""
from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.llm.factory import get_llm_provider

logger = structlog.get_logger(__name__)


class SEOAgent(Agent):
    name = "seo_agent"
    max_retries = 2

    def __init__(self, llm=None) -> None:
        self.llm = llm or get_llm_provider()

    def _execute(self, context: AgentContext) -> Any:
        if context.script is None:
            raise ValueError("ScriptAgent must run before SEOAgent")
        if context.research is None:
            raise ValueError("ResearchAgent must run before SEOAgent")

        from app.seo.metadata_generator import SEOGenerator
        gen = SEOGenerator(project_id=context.project_id, llm=self.llm)
        result = gen.generate(
            topic=context.chosen_topic or context.topic,
            script=context.script,
            research=context.research,
            language=context.language,
            style=context.style,
        )
        context.seo = result

        seo_path = context.output_dir / "seo.json"
        seo_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        logger.info(
            "seo_complete",
            project=context.project_id,
            title=result.best_title,
            tags=len(result.tags),
        )
        return result
