"""
Script generator — converts research into a structured YouTube script.
Uses LLM with a validated Pydantic output schema.
"""
from __future__ import annotations

import json
import re

import structlog

from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.database.models import Scene, Script
from app.database.session import get_session
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.research.schemas import ResearchResult
from app.script.schemas import ScriptResult

logger = structlog.get_logger(__name__)

_PROMPT_PATH = settings.prompt_dir / "script_prompt.txt"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Write a YouTube script for the topic: {topic}. "
        "Language: {language}. Style: {style}. "
        "Target duration: {target_duration_minutes} minutes. "
        "Research: {research_json}. "
        "Return ONLY valid JSON."
    )


class ScriptGenerator:
    """
    Generates a structured YouTube script from research data.

    Args:
        project_id: The owning project.
        llm: Optional pre-built LLM provider.
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
        research: ResearchResult,
        target_duration_seconds: int = 480,
        language: str = "English",
        style: str = "documentary",
    ) -> ScriptResult:
        """
        Generate a script. Returns cached result if already generated (resumable).
        """
        logger.info("script_generation_started", project=self.project_id, topic=topic)

        existing = self._load_existing()
        if existing is not None:
            logger.info("script_loaded_from_db", project=self.project_id)
            return existing

        target_minutes = round(target_duration_seconds / 60, 1)
        target_words = int(settings.words_per_minute * target_minutes)

        # Use simple string replacement — prompt file contains JSON {braces}
        # that would break str.format().
        research_json_str = json.dumps(research.model_dump(), indent=2)[:4000]
        prompt = (
            _load_prompt()
            .replace("{topic}", topic)
            .replace("{language}", language)
            .replace("{style}", style)
            .replace("{target_duration_minutes}", str(target_minutes))
            .replace("{target_words}", str(target_words))
            .replace("{research_json}", research_json_str)
        )

        raw, response = self.llm.generate_json(
            prompt,
            schema_hint="ScriptResult",
            temperature=0.7,
            max_tokens=settings.llm_max_tokens,
        )

        # Record cost from the same call — no second LLM request needed
        self.cost_tracker.record(
            provider=self.llm.provider_name,
            model=getattr(self.llm, "model", "unknown"),
            operation="script",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        result = _align_numbered_title(ScriptResult.model_validate(raw))
        self._save(result)

        logger.info(
            "script_generation_complete",
            project=self.project_id,
            title=result.title,
            sections=len(result.sections),
            words=result.word_count,
            duration_s=result.estimated_duration_seconds,
        )
        return result

    # ── private ────────────────────────────────────────────────────────────

    def _load_existing(self) -> ScriptResult | None:
        with get_session() as session:
            row = (
                session.query(Script)
                .filter_by(project_id=self.project_id)
                .order_by(Script.version.desc())
                .first()
            )
            if row is None or row.raw_json is None:
                return None
            try:
                return _align_numbered_title(ScriptResult.model_validate(row.raw_json))
            except Exception:
                return None

    def _save(self, result: ScriptResult) -> None:
        with get_session() as session:
            script_row = Script(
                project_id=self.project_id,
                title=result.title,
                hook=result.hook,
                conclusion=result.conclusion,
                call_to_action=result.call_to_action,
                estimated_duration_seconds=result.estimated_duration_seconds,
                word_count=result.word_count,
                raw_json=result.model_dump(),
            )
            session.add(script_row)
            session.flush()  # get script_row.id

            for section in result.sections:
                session.add(
                    Scene(
                        project_id=self.project_id,
                        script_id=script_row.id,
                        scene_order=section.id,
                        narration=section.narration,
                        duration_seconds=float(section.duration_seconds),
                    )
                )


def _align_numbered_title(result: ScriptResult) -> ScriptResult:
    """Never promise a numbered list that the generated script does not contain."""
    match = re.match(r"^(\s*)(\d+)(\b.*)$", result.title)
    if not match or not result.sections:
        return result
    actual = len(result.sections)
    promised = int(match.group(2))
    if promised == actual:
        return result
    title = f"{match.group(1)}{actual}{match.group(3)}"
    logger.warning("numbered_title_aligned", promised=promised, actual=actual, title=title)
    return result.model_copy(update={"title": title})
