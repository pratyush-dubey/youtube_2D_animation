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
import hashlib
import re
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

        topic = context.chosen_topic or context.topic
        research = context.research
        people_list = _person_names(getattr(research, "people", []) if research else [])

        cache_path = context.output_dir / "characters.json"
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data.get("characters") or data.get("settings"):
                    data = _normalise_character_bible(
                        _attach_references(data, context.output_dir, people_list)
                    )
                    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    _write_reference_attribution(context.output_dir, data)
                    context.character_sheet = data
                    logger.info(
                        "characters_loaded_from_cache",
                        project=context.project_id,
                        characters=len(data.get("characters", [])),
                    )
                    return data
            except Exception:
                pass

        research_summary = ""
        if research is not None:
            facts = getattr(research, "facts", []) or []
            research_summary = " ".join(str(f) for f in facts[:10])

        # Never invent a presenter or substitute character. A video without an
        # explicitly researched person simply has no character layer.
        if not people_list:
            sheet = {"characters": [], "settings": []}
            cache_path.write_text(json.dumps(sheet, indent=2), encoding="utf-8")
            context.character_sheet = sheet
            return sheet

        prompt = (
            _load_prompt()
            .replace("{topic}", topic)
            .replace("{style}", context.style)
            .replace("{people}", ", ".join(str(p) for p in people_list[:10]))
            .replace("{research_summary}", research_summary[:2000])
        )

        try:
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
        except Exception as exc:
            logger.warning("character_generation_fallback", error=str(exc))
            raw = _fallback_character_sheet(topic, people_list)

        # Normalise: ensure both keys exist
        sheet: dict = {
            "characters": raw.get("characters", []),
            "settings": raw.get("settings", []),
        }
        sheet = _normalise_character_bible(
            _attach_references(sheet, context.output_dir, people_list)
        )

        cache_path.write_text(json.dumps(sheet, indent=2), encoding="utf-8")
        _write_reference_attribution(context.output_dir, sheet)
        context.character_sheet = sheet

        logger.info(
            "characters_complete",
            project=context.project_id,
            characters=len(sheet["characters"]),
            settings_count=len(sheet["settings"]),
        )
        return sheet


def _fallback_character_sheet(topic: str, people: list[str]) -> dict:
    """Preserve researched identities without inventing facial characteristics."""
    return {
        "characters": [
            {
                "name": name,
                "role": "researched person",
                "visual": (
                    f"Identity must match the verified reference portrait of {name}; "
                    "do not invent, blend, beautify, or substitute facial features"
                ),
            }
            for name in people
        ],
        "settings": [
            {
                "name": topic,
                "visual": "Cinematic location plate grounded in the researched time and place",
            }
        ],
    }


def _person_names(people) -> list[str]:
    names: list[str] = []
    for person in people or []:
        if isinstance(person, str):
            name = person
        elif isinstance(person, dict):
            name = person.get("name", "")
        else:
            name = getattr(person, "name", "")
        name = str(name).strip()
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return names


def _normalise_character_bible(sheet: dict) -> dict:
    """Persist identity, wardrobe, proportions, expressions, poses, and style."""
    characters = []
    for raw in sheet.get("characters", []):
        if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
            continue
        entry = dict(raw)
        name = str(entry["name"]).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "character"
        entry.setdefault("character_id", f"{slug}-{hashlib.sha256(name.casefold().encode()).hexdigest()[:8]}")
        entry.setdefault("reference_asset", entry.get("reference_image"))
        entry.setdefault("appearance", entry.get("visual", "identity locked to reference asset"))
        entry.setdefault("clothing", entry.get("clothing", "preserve wardrobe defined in visual description"))
        entry.setdefault("colors", entry.get("colors", []))
        entry.setdefault("facial_features", entry.get("facial_features", "match verified reference; do not invent"))
        entry.setdefault("body_proportions", entry.get("body_proportions", "consistent across every pose"))
        entry.setdefault("style", entry.get("style", "cinematic layered 2D cutout"))
        entry.setdefault("expressions", [
            "neutral", "happy", "sad", "angry", "fear", "surprised", "confused", "thinking",
        ])
        entry.setdefault("poses", [
            "front", "three-quarter", "profile", "walking", "reaction", "speaking",
        ])
        characters.append(entry)
    return {
        **sheet,
        "character_bible_version": 1,
        "characters": characters,
        "settings": sheet.get("settings", []),
    }


def _attach_references(sheet: dict, output_dir: Path, people: list[str]) -> dict:
    from app.images.character_references import attach_character_references

    try:
        return attach_character_references(sheet, output_dir, people)
    except Exception as exc:
        logger.warning("character_reference_lookup_failed", error=str(exc))
        # Still enforce the researched-name allowlist when Wikimedia is unavailable.
        allowed = {name.casefold(): name for name in people}
        characters = []
        for raw in sheet.get("characters", []):
            entry = dict(raw) if isinstance(raw, dict) else {}
            canonical = allowed.get(str(entry.get("name", "")).casefold())
            if canonical:
                entry["name"] = canonical
                entry["identity_reference_status"] = "lookup-failed"
                characters.append(entry)
        return {"characters": characters, "settings": sheet.get("settings", [])}


def _write_reference_attribution(output_dir: Path, sheet: dict) -> None:
    lines: list[str] = []
    for character in sheet.get("characters", []):
        source = str(character.get("reference_file_url", "")).strip()
        if not source:
            continue
        lines.extend([
            str(character.get("name", "Unknown person")),
            f"Source: {source}",
            f"License: {character.get('reference_license', 'unknown')}",
            f"Artist: {character.get('reference_artist', '') or 'not listed'}",
            f"Credit: {character.get('reference_attribution', '') or 'see source page'}",
            "",
        ])
    if lines:
        path = output_dir / "characters" / "attribution.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
