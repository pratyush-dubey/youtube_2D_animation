"""
StoryboardAgent — converts the script into a scene-by-scene storyboard
with image prompts, camera motions, transitions, and SFX cues.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.llm.factory import get_llm_provider
from app.script.schemas import ScriptResult

logger = structlog.get_logger(__name__)

_PROMPT_PATH = settings.prompt_dir / "storyboard_prompt.txt"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Convert this script into a 2D animated video storyboard. "
        "Topic: {topic}. Style: {style}. Aspect ratio: {aspect_ratio}. "
        "Character sheet: {character_sheet}. "
        "Script: {script_json}. "
        "Return JSON with keys: total_scenes, total_duration_seconds, scenes (array). "
        "Each scene has: scene_id, duration_seconds, narration, visual_description, "
        "image_prompt, animation_type, camera_motion, text_overlay, transition, "
        "music_mood, sfx. Return ONLY valid JSON."
    )


class StoryboardAgent(Agent):
    name = "storyboard_agent"
    max_retries = 2

    def __init__(self, llm=None) -> None:
        self.llm = llm or get_llm_provider()
        self.cost_tracker: CostTracker | None = None

    def _execute(self, context: AgentContext) -> list[dict]:
        if context.script is None:
            raise ValueError("ScriptAgent must run before StoryboardAgent")

        self.cost_tracker = CostTracker(context.project_id)

        # Check cache
        storyboard_path = context.output_dir / "storyboard.json"
        if storyboard_path.exists():
            try:
                data = json.loads(storyboard_path.read_text(encoding="utf-8"))
                scenes = data.get("scenes", [])
                if scenes:
                    context.storyboard = scenes
                    logger.info("storyboard_loaded_from_cache", project=context.project_id)
                    return scenes
            except Exception:
                pass

        topic = context.chosen_topic or context.topic
        script: ScriptResult = context.script

        # Serialise character sheet to a compact string for injection
        import json as _json
        char_sheet = context.character_sheet or {}
        char_sheet_str = _json.dumps(char_sheet, ensure_ascii=False)[:1500] if char_sheet else "none"

        prompt = (
            _load_prompt()
            .replace("{topic}", topic)
            .replace("{style}", context.style)
            .replace("{aspect_ratio}", context.aspect_ratio)
            .replace("{character_sheet}", char_sheet_str)
            .replace("{script_json}", script.model_dump_json()[:5000])
        )

        raw, response = self.llm.generate_json(
            prompt, schema_hint="Storyboard", temperature=0.6, max_tokens=4096
        )
        self.cost_tracker.record(
            provider=self.llm.provider_name,
            model=getattr(self.llm, "model", "unknown"),
            operation="storyboard",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        scenes = raw.get("scenes", [])
        if not scenes:
            # If raw itself is a list
            scenes = raw if isinstance(raw, list) else []

        # Validate and normalise each scene
        scenes = [_normalise_scene(s, i) for i, s in enumerate(scenes, 1)]

        storyboard_path.write_text(
            json.dumps({"total_scenes": len(scenes), "scenes": scenes}, indent=2),
            encoding="utf-8",
        )
        context.storyboard = scenes
        logger.info("storyboard_complete", project=context.project_id, scenes=len(scenes))
        return scenes


# Animation types supported by the video compositor (keep in sync with
# _ken_burns_filter in video_edit_agent.py)
_VALID_ANIMATIONS = {
    "zoom-in", "zoom-out", "pan-left", "pan-right",
    "pan-up", "pan-down", "ken-burns", "drift-right", "static",
}

# Map LLM aliases → canonical names
_ANIMATION_ALIASES: dict[str, str] = {
    "slow-zoom-in":   "zoom-in",
    "slow-zoom-out":  "zoom-out",
    "slow zoom in":   "zoom-in",
    "slow zoom out":  "zoom-out",
    "zoom in":        "zoom-in",
    "zoom out":       "zoom-out",
    "pan left":       "pan-left",
    "pan right":      "pan-right",
    "pan up":         "pan-up",
    "pan down":       "pan-down",
    "ken burns":      "ken-burns",
    "kenburns":       "ken-burns",
    "drift":          "drift-right",
    "none":           "static",
    "still":          "static",
    "freeze":         "static",
}

# Rotation of varied motion types used when the LLM doesn't specify one
# or returns "static" for every scene.
_MOTION_CYCLE = [
    "zoom-in", "pan-right", "ken-burns", "zoom-out",
    "pan-left", "drift-right", "zoom-in", "pan-up",
]


def _resolve_animation(raw: str | None, idx: int) -> str:
    """Normalise LLM animation string to a supported type."""
    if not raw:
        return _MOTION_CYCLE[(idx - 1) % len(_MOTION_CYCLE)]
    key = raw.strip().lower()
    # Exact match
    if key in _VALID_ANIMATIONS:
        return key
    # Alias lookup
    if key in _ANIMATION_ALIASES:
        return _ANIMATION_ALIASES[key]
    # Partial / contains match
    for alias, canonical in _ANIMATION_ALIASES.items():
        if alias in key:
            return canonical
    for name in _VALID_ANIMATIONS:
        if name in key:
            return name
    # Fallback: rotate through motion cycle so scenes don't all look identical
    return _MOTION_CYCLE[(idx - 1) % len(_MOTION_CYCLE)]


def _normalise_scene(s: dict, idx: int) -> dict:
    animation = _resolve_animation(s.get("animation_type"), idx)
    return {
        "scene_id": s.get("scene_id", idx),
        "duration_seconds": float(s.get("duration_seconds", 8.0)),
        "narration": s.get("narration", ""),
        "visual_description": s.get("visual_description", ""),
        "image_prompt": s.get("image_prompt", "2D flat illustration, editorial style"),
        "animation_type": animation,
        "camera_motion": s.get("camera_motion", "slow-zoom-in"),
        "text_overlay": s.get("text_overlay"),
        "transition": s.get("transition", "cut"),
        "music_mood": s.get("music_mood", "calm"),
        "sfx": s.get("sfx", []),
    }
