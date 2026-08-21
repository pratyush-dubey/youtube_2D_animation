"""
ScriptAgent — transforms research into a compelling YouTube script.
Uses the configured LLM (Gemini or OpenAI — no Ollama in cloud mode).
"""
from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.llm.factory import get_llm_provider
from app.script.script_generator import ScriptGenerator

logger = structlog.get_logger(__name__)


class ScriptAgent(Agent):
    name = "script_agent"
    max_retries = 2

    def __init__(self, llm=None) -> None:
        self.llm = llm or get_llm_provider()

    def _execute(self, context: AgentContext) -> Any:
        if context.research is None:
            raise ValueError("ResearchAgent must run before ScriptAgent")

        topic = context.chosen_topic or context.topic
        gen = ScriptGenerator(project_id=context.project_id, llm=self.llm)
        result = gen.generate(
            topic=topic,
            research=context.research,
            target_duration_seconds=context.target_duration_seconds,
            language=context.language,
            style=context.style,
        )
        context.script = result

        # Write to disk for inspection / resume
        script_path = context.output_dir / "script.json"
        script_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        logger.info(
            "script_complete",
            project=context.project_id,
            title=result.title,
            sections=len(result.sections),
            words=result.word_count,
        )
        return result
