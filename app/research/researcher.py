"""
Research agent — Phase 1 implementation.

Phase 1: LLM-only research (no web crawling).
         The LLM is prompted to draw on its training knowledge.

Phase 2+ will add: DuckDuckGo search, Wikipedia API, article extraction via trafilatura.

The research agent never fabricates sources — if web research is not enabled,
all sources are clearly marked as "LLM training knowledge".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.database.models import Research, Source
from app.database.session import get_session
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.research.schemas import ResearchResult

logger = structlog.get_logger(__name__)

_PROMPT_PATH = settings.prompt_dir / "research_prompt.txt"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    # Inline fallback so the system works even if prompts/ is missing
    return (
        "Research the following topic and return a JSON object with keys: "
        "topic, summary, facts, claims, statistics, dates, people, locations, "
        "uncertain_claims, key_questions, suggested_sections. "
        "Topic: {topic}. Language: {language}. "
        "Return ONLY valid JSON."
    )


class Researcher:
    """
    Orchestrates research for a project topic.

    Args:
        project_id: The project this research belongs to.
        llm: Optional pre-built LLM provider (defaults to configured provider).
        extra_context: Optional list of web-sourced facts (dicts with 'source'
                       and 'content' keys) gathered by the ResearchAgent before
                       calling the LLM.  When present they are appended to the
                       prompt so the LLM can ground its answer in real data.
    """

    def __init__(
        self,
        project_id: str,
        llm: LLMProvider | None = None,
        extra_context: list[dict] | None = None,
    ) -> None:
        self.project_id = project_id
        self.llm = llm or get_llm_provider()
        self.cost_tracker = CostTracker(project_id)
        self.extra_context: list[dict] = extra_context or []

    def run(self, topic: str, language: str = "English") -> ResearchResult:
        """
        Run the research stage.
        Returns a validated ResearchResult and persists it to the database.
        Skips if research already exists for this project (resumable).
        """
        logger.info("research_started", project=self.project_id, topic=topic)

        # Check for existing research (resume support)
        existing = self._load_existing()
        if existing is not None:
            logger.info("research_loaded_from_db", project=self.project_id)
            return existing

        prompt_template = _load_prompt()
        # Use simple string replacement instead of str.format() because the
        # prompt file contains JSON examples with {braces} that confuse format().
        prompt = (
            prompt_template
            .replace("{topic}", topic)
            .replace("{language}", language)
        )

        # Prepend real web facts when available so the LLM is grounded in them
        if self.extra_context:
            web_block = "\n\n### Web Research Context (use these facts):\n"
            for item in self.extra_context[:10]:  # cap at 10 items
                src = item.get("source", "web")
                content = item.get("content", "")[:600]
                web_block += f"[{src}]: {content}\n"
            prompt = web_block + "\n" + prompt

        raw, response = self.llm.generate_json(
            prompt,
            schema_hint="ResearchResult",
            temperature=0.3,   # lower temperature for factual research
            max_tokens=1200,
            max_retries=3,
        )

        # Record cost from the same call — no second LLM request needed
        self.cost_tracker.record(
            provider=self.llm.provider_name,
            model=getattr(self.llm, "model", "unknown"),
            operation="research",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        # Inject the topic as a fallback in case the LLM omits it
        if "topic" not in raw or not raw.get("topic"):
            raw["topic"] = topic
        result = ResearchResult.model_validate(raw)
        self._save(result, topic)

        logger.info(
            "research_complete",
            project=self.project_id,
            facts=len(result.facts),
            claims=len(result.claims),
        )
        return result

    # ── private ────────────────────────────────────────────────────────────

    def _load_existing(self) -> ResearchResult | None:
        with get_session() as session:
            row = (
                session.query(Research)
                .filter_by(project_id=self.project_id)
                .first()
            )
            if row is None:
                return None
            # Reconstruct from stored dicts — model_validate handles both
            # dict-of-dicts (from JSON column) and plain lists gracefully.
            return ResearchResult.model_validate({
                "topic": row.raw_text or "",
                "summary": "",
                "facts": row.facts or [],
                "claims": row.claims or [],
                "statistics": row.statistics or [],
                "dates": row.dates or [],
                "people": row.people or [],
                "locations": row.locations or [],
                "uncertain_claims": row.uncertain_claims or [],
            })

    def _save(self, result: ResearchResult, topic: str) -> None:
        with get_session() as session:
            # Upsert research row
            row = (
                session.query(Research)
                .filter_by(project_id=self.project_id)
                .first()
            )
            if row is None:
                row = Research(project_id=self.project_id)
                session.add(row)

            row.facts = [f.model_dump() for f in result.facts]
            row.claims = [c.model_dump() for c in result.claims]
            row.statistics = [s.model_dump() for s in result.statistics]
            row.dates = [d.model_dump() for d in result.dates]
            row.people = [p.model_dump() for p in result.people]
            row.locations = [lo.model_dump() for lo in result.locations]
            row.uncertain_claims = [u.model_dump() for u in result.uncertain_claims]
            row.raw_text = topic

            # Add a synthetic source entry so it's clear this is LLM knowledge
            session.add(
                Source(
                    project_id=self.project_id,
                    title="LLM Training Knowledge",
                    author=self.llm.provider_name,
                    accessed_at=datetime.now(timezone.utc).isoformat(),
                    credibility_score=0.7,
                    summary=(
                        "Research generated from LLM training data. "
                        "No live web sources were consulted in Phase 1."
                    ),
                )
            )
