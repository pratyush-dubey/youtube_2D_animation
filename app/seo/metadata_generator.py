"""
SEO metadata generator.
Produces optimised YouTube title, description, tags, hashtags, and chapters
using the configured LLM provider.
"""
from __future__ import annotations

import json

import structlog

from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.database.models import Metadata
from app.database.session import get_session
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.research.schemas import ResearchResult
from app.script.schemas import ScriptResult
from app.seo.schemas import SEOMetadata

logger = structlog.get_logger(__name__)

_PROMPT_PATH = settings.prompt_dir / "seo_prompt.txt"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Generate YouTube SEO metadata for topic: {topic}. "
        "Title: {script_title}. Return JSON with keys: "
        "title_candidates, best_title, description, tags, hashtags, chapters. "
        "Return ONLY valid JSON."
    )


def _summarise_research(research: ResearchResult) -> str:
    parts = []
    if research.summary:
        parts.append(research.summary)
    for f in research.facts[:5]:
        parts.append(f"- {f.fact}")
    return "\n".join(parts) or "General educational content."


def _key_facts_str(research: ResearchResult) -> str:
    facts = [f.fact for f in research.facts[:8]]
    return "; ".join(facts) if facts else "N/A"


class SEOGenerator:
    """
    Generates YouTube SEO metadata from topic + script + research.
    Results are persisted to the database and cached for resume.
    """

    def __init__(
        self,
        project_id: str,
        llm: LLMProvider | None = None,
    ) -> None:
        self.project_id = project_id
        self.llm = llm or get_llm_provider()
        self.cost_tracker = CostTracker(project_id)

    def generate(
        self,
        topic: str,
        script: ScriptResult,
        research: ResearchResult,
        language: str = "English",
        style: str = "documentary",
    ) -> SEOMetadata:
        logger.info("seo_generation_started", project=self.project_id, topic=topic)

        # Resume support
        existing = self._load_existing()
        if existing is not None:
            logger.info("seo_loaded_from_db", project=self.project_id)
            return existing

        # Build chapters from script sections
        chapters = _build_chapters(script)

        # Build prompt
        duration_seconds = script.estimated_duration_seconds
        summary_text = _summarise_research(research)
        key_facts = _key_facts_str(research)

        prompt = (
            _load_prompt()
            .replace("{topic}", topic)
            .replace("{script_title}", script.title)
            .replace("{script_summary}", summary_text[:1000])
            .replace("{key_facts}", key_facts[:500])
            .replace("{duration_seconds}", str(duration_seconds))
            .replace("{language}", language)
            .replace("{style}", style)
        )

        raw, response = self.llm.generate_json(
            prompt,
            schema_hint="SEOMetadata",
            temperature=0.6,
            max_tokens=settings.llm_max_tokens,
        )

        self.cost_tracker.record(
            provider=self.llm.provider_name,
            model=getattr(self.llm, "model", "unknown"),
            operation="seo",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        # Inject pre-built chapters if LLM didn't produce them
        if not raw.get("chapters"):
            raw["chapters"] = [c.model_dump() for c in chapters]

        # Ensure best_title falls back to script title
        if not raw.get("best_title"):
            raw["best_title"] = script.title

        result = SEOMetadata.model_validate(raw)
        self._save(result)

        logger.info(
            "seo_generation_complete",
            project=self.project_id,
            title=result.best_title,
            tags=len(result.tags),
            chapters=len(result.chapters),
        )
        return result

    # ── private ────────────────────────────────────────────────────────────

    def _load_existing(self) -> SEOMetadata | None:
        with get_session() as session:
            row = (
                session.query(Metadata)
                .filter_by(project_id=self.project_id)
                .first()
            )
            if row is None or not row.title:
                return None
            try:
                return SEOMetadata.model_validate({
                    "best_title": row.title or "",
                    "description": row.description or "",
                    "tags": row.tags or [],
                    "hashtags": row.hashtags or [],
                    "chapters": row.chapters or [],
                })
            except Exception:
                return None

    def _save(self, result: SEOMetadata) -> None:
        with get_session() as session:
            row = (
                session.query(Metadata)
                .filter_by(project_id=self.project_id)
                .first()
            )
            if row is None:
                row = Metadata(project_id=self.project_id)
                session.add(row)

            row.title = result.best_title
            row.description = result.description
            row.tags = result.tags
            row.hashtags = result.hashtags
            row.chapters = [c.model_dump() for c in result.chapters]
            row.title_score = max(
                (c.total_score for c in result.title_candidates), default=0
            )


def _build_chapters(script: ScriptResult) -> list:
    """Build chapter timestamps from script sections."""
    from app.seo.schemas import Chapter
    chapters = [Chapter(time="0:00", label="Intro")]
    elapsed = 0
    for section in script.sections:
        if elapsed > 0:
            minutes = elapsed // 60
            seconds = elapsed % 60
            chapters.append(
                Chapter(time=f"{minutes}:{seconds:02d}", label=section.title or f"Part {section.id}")
            )
        elapsed += int(section.duration_seconds)
    return chapters
