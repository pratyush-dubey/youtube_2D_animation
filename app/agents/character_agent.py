"""
CharacterAgent — builds a visual character sheet for key people in the video.

Runs after ResearchAgent, before StoryboardAgent.
Produces context.character_sheet so that every subsequent image prompt
references consistent character appearances (clothing, hair, build, etc.)
and key settings (cities, buildings).

The character sheet is persisted to output_dir/characters.json so it
survives resume / re-runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.llm.factory import get_llm_provider

logger = structlog.get_logger(__name__)

_PROMPT_PATH = settings.prompt_dir / "character_prompt.txt"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    # Inline fallback (should never be needed)
    return (
        "Topic: {topic}. Style: {style}. People: {people}. "
        "Research: {research_summary}. "
        "Return JSON with keys 'characters' (list of name/role/visual) and "
        "'settings' (list of name/visual). Return ONLY valid JSON."
    )


class CharacterAgent(Agent):
    name = "character_agent"
    max_retries = 2

    def __init__(self, llm=None) -> None:
        self.llm = llm or get_llm_provider()
        self.cost_tracker: CostTracker | None = None

    def _execute(self, context: AgentContext) -> dict:
        self.cost_tracker = CostTracker(context.project_id)

        cache_path = context.output_dir / "characters.json"
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data.get("characters") or data.get("settings"):
                    context.character_sheet = data
                    logger.info(
                        "characters_loaded_from_cache",
                        project=context.project_id,
                        characters=len(data.get("characters", [])),
                    )
                    return data
            except Exception:
                pass

        topic = context.chosen_topic or context.topic
        research = context.research

        # Extract people list from research if available
        people_list: list[str] = []
        research_summary = ""
        if research is not None:
            people_list = getattr(research, "people", []) or []
            facts = getattr(research, "facts", []) or []
            research_summary = " ".join(str(f) for f in facts[:10])

        # If research found no people, derive from topic name itself
        if not people_list:
            people_list = [topic]

        prompt = (
            _load_prompt()
            .replace("{topic}", topic)
            .replace("{style}", context.style)
            .replace("{people}", ", ".join(str(p) for p in people_list[:10]))
            .replace("{research_summary}", research_summary[:2000])
        )

        raw, response = self.llm.generate_json(
            prompt,
            schema_hint="CharacterSheet",
            temperature=0.4,
            max_tokens=2048,
        )
        self.cost_tracker.record(
            provider=self.llm.provider_name,
            model=getattr(self.llm, "model", "unknown"),
            operation="characters",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        # Normalise: ensure both keys exist
        sheet: dict = {
            "characters": raw.get("characters", []),
            "settings": raw.get("settings", []),
        }

        cache_path.write_text(json.dumps(sheet, indent=2), encoding="utf-8")
        context.character_sheet = sheet

        logger.info(
            "characters_complete",
            project=context.project_id,
            characters=len(sheet["characters"]),
            settings_count=len(sheet["settings"]),
        )
        return sheet
