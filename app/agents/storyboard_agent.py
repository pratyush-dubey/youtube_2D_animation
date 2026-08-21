"""
StoryboardAgent — converts the script into a scene-by-scene storyboard
with image prompts, camera motions, transitions, and SFX cues.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

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
                    scenes = _prepare_scenes(scenes)
                    scenes = _ensure_script_sections(scenes, context.script, context.topic)
                    context.storyboard = scenes
                    _write_storyboard(storyboard_path, scenes)
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
            prompt,
            schema_hint="Storyboard",
            temperature=0.55,
            max_tokens=settings.llm_max_tokens,
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
        scenes = _prepare_scenes(scenes)
        scenes = _ensure_script_sections(scenes, script, topic)

        _write_storyboard(storyboard_path, scenes)
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
        "voice_emotion": _resolve_voice_emotion(
            s.get("voice_emotion") or s.get("music_mood")
        ),
        "sfx": s.get("sfx", []),
        "asset_type": _resolve_asset_type(s, idx),
        "overlay_style": s.get("overlay_style", "location"),
        "motion_intensity": s.get("motion_intensity", "medium"),
        "accent_color": s.get("accent_color", "amber"),
        "character_name": s.get("character_name"),
        "character_action": s.get("character_action"),
        "character_motion": _resolve_character_motion(s.get("character_motion")),
        "character_position": _resolve_character_position(s.get("character_position")),
        "character_scale": _resolve_character_scale(s.get("character_scale")),
        "character_is_fictional": bool(s.get("character_is_fictional", False)),
        "shots": s.get("shots", []),
        "layers": s.get("layers", []),
        "render_quality": str(s.get("render_quality", "FINAL")).upper(),
        "visual_quality": str(s.get("visual_quality", settings.visual_quality)).upper(),
        "parent_scene_id": s.get("parent_scene_id", s.get("scene_id", idx)),
        "visual_beat": int(s.get("visual_beat", 1)),
    }


def _resolve_character_motion(raw: str | None) -> str | None:
    if not raw:
        return None
    from app.video.character_motion import CHARACTER_MOTIONS
    key = str(raw).strip().lower().replace("_", "-")
    return key if key in CHARACTER_MOTIONS else "idle-breathe"


def _resolve_voice_emotion(raw: str | None) -> str:
    allowed = {
        "mysterious", "tense", "uplifting", "calm", "dramatic",
        "curious", "serious", "hopeful", "eerie",
    }
    key = str(raw or "serious").strip().lower()
    return key if key in allowed else "serious"


def _resolve_character_position(raw: str | None) -> str:
    key = str(raw or "right").strip().lower()
    return key if key in {"left", "center", "right"} else "right"


def _resolve_character_scale(raw) -> float:
    try:
        return min(max(float(raw or 0.72), 0.35), 1.0)
    except (TypeError, ValueError):
        return 0.72


_SHOT_TYPES = (
    "wide establishing shot",
    "medium subject shot",
    "close-up detail",
    "top-down explanatory view",
    "dramatic silhouette composition",
    "diagram-like visual metaphor",
)


def _write_storyboard(path: Path, scenes: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "storyboard_version": 3,
                "total_scenes": len(scenes),
                "total_duration_seconds": round(
                    sum(float(s.get("duration_seconds", 0)) for s in scenes), 2
                ),
                "scenes": scenes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _prepare_scenes(raw_scenes: list[dict]) -> list[dict]:
    """Normalise and turn narration paragraphs into short visual beats.

    A single generated image should not carry a 20-45 second paragraph.  Each
    beat is capped at roughly 18 spoken words (about 5-8 seconds), receives a
    distinct composition instruction, and keeps the original narration order.
    """
    prepared: list[dict] = []
    for source_index, raw in enumerate(raw_scenes, 1):
        scene = _normalise_scene(raw, source_index)
        narration = scene["narration"].strip()
        chunks = _split_narration(narration)
        if not chunks:
            chunks = [""]

        source_duration = max(float(scene["duration_seconds"]), 3.0)
        total_words = max(sum(len(c.split()) for c in chunks), 1)
        for beat_index, chunk in enumerate(chunks, 1):
            beat = dict(scene)
            beat["scene_id"] = len(prepared) + 1
            beat["parent_scene_id"] = scene["parent_scene_id"]
            beat["visual_beat"] = beat_index
            beat["narration"] = chunk
            word_share = max(len(chunk.split()), 1) / total_words
            beat["duration_seconds"] = round(
                min(8.0, max(3.0, source_duration * word_share)), 2
            )
            shot = _SHOT_TYPES[(len(prepared)) % len(_SHOT_TYPES)]
            if len(chunks) > 1:
                beat["visual_description"] = (
                    f"{scene['visual_description']} Visual beat: {chunk} Composition: {shot}."
                ).strip()
                beat["image_prompt"] = (
                    f"{scene['image_prompt']}. Show this exact visual beat: {chunk}. "
                    f"Composition: {shot}; clear focal subject; readable silhouette; no text."
                )
                beat["text_overlay"] = scene["text_overlay"] if beat_index == 1 else None
                beat["sfx"] = scene["sfx"] if beat_index == 1 else []
                beat["transition"] = scene["transition"] if beat_index == 1 else "cut"
                beat["animation_type"] = _MOTION_CYCLE[
                    (len(prepared)) % len(_MOTION_CYCLE)
                ]
                beat["asset_type"] = _beat_asset_type(scene["asset_type"], beat_index)
            from app.video.timeline import build_production_scene
            prepared.append(build_production_scene(beat))
    return prepared


def _split_narration(text: str, max_words: int = 18) -> list[str]:
    """Split prose at punctuation, then at clauses, without dropping words."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        while len(words) > max_words:
            split_at = max_words
            for i in range(max_words, max(7, max_words // 2), -1):
                if words[i - 1].endswith((",", ";", ":", "—", "–")):
                    split_at = i
                    break
            chunks.append(" ".join(words[:split_at]).strip())
            words = words[split_at:]
        if words:
            tail = " ".join(words).strip()
            if chunks and len(tail.split()) < 5 and len(chunks[-1].split()) + len(words) <= 22:
                chunks[-1] = f"{chunks[-1]} {tail}"
            else:
                chunks.append(tail)
    return chunks


def _ensure_script_sections(
    scenes: list[dict], script: ScriptResult, topic: str
) -> list[dict]:
    """Add deterministic visual beats for any section the LLM omitted."""
    all_tokens = _text_tokens(" ".join(s.get("narration", "") for s in scenes))
    missing = []
    for section in script.sections:
        expected = _text_tokens(section.narration)
        coverage = len(expected & all_tokens) / max(len(expected), 1)
        if coverage < 0.65:
            missing.append(section)
    if not missing:
        return scenes

    # Keep the conclusion/CTA last when an old cached storyboard omitted a body section.
    insert_at = len(scenes)
    closing_tokens = _text_tokens(f"{script.conclusion} {script.call_to_action}")
    for index, scene in enumerate(scenes):
        scene_tokens = _text_tokens(scene.get("narration", ""))
        if scene_tokens and len(scene_tokens & closing_tokens) / len(scene_tokens) >= 0.5:
            insert_at = index
            break

    additions: list[dict] = []
    for section in missing:
        raw = {
            "scene_id": section.id,
            "duration_seconds": float(section.duration_seconds),
            "narration": section.narration,
            "visual_description": (
                f"A sequence of accurate editorial visuals explaining {section.title}."
            ),
            "image_prompt": (
                f"{topic} — {section.title}. Visualize this exact fact: {section.narration}"
            ),
            "animation_type": "ken-burns",
            "camera_motion": "slow-zoom-in",
            "text_overlay": section.title,
            "transition": "dissolve",
            "music_mood": "curious",
            "sfx": ["whoosh"],
        }
        additions.extend(_prepare_scenes([raw]))

    merged = scenes[:insert_at] + additions + scenes[insert_at:]
    for scene_id, scene in enumerate(merged, 1):
        scene["scene_id"] = scene_id
    logger.warning(
        "storyboard_sections_recovered",
        missing=[section.title for section in missing],
        added_beats=len(additions),
    )
    return merged


def _text_tokens(text: str) -> set[str]:
    stop = {"the", "and", "for", "that", "with", "from", "this", "into", "are", "was"}
    return {
        token for token in re.findall(r"[a-z0-9]+", str(text).lower())
        if len(token) > 2 and token not in stop
    }


_ASSET_TYPES = {
    "cinematic-reenactment", "archival-portrait", "archival-footage",
    "animated-map", "newspaper-document", "evidence-board", "date-card",
    "location-card", "diagram", "atmospheric-detail",
}


def _resolve_asset_type(scene: dict, idx: int) -> str:
    raw = str(scene.get("asset_type", "")).strip().lower().replace("_", "-")
    if raw in _ASSET_TYPES:
        return raw
    text = f"{scene.get('narration', '')} {scene.get('visual_description', '')}".lower()
    if any(word in text for word in ("map", "route", "border", "country", "city", "state")):
        return "animated-map"
    if any(word in text for word in ("newspaper", "report", "article", "document", "file")):
        return "newspaper-document"
    if any(word in text for word in ("timeline", "date", "year", "century", "older")):
        return "date-card"
    if any(word in text for word in ("portrait", "photograph", "archival", "historical")):
        return "archival-portrait"
    cycle = (
        "cinematic-reenactment", "atmospheric-detail", "archival-footage",
        "evidence-board", "cinematic-reenactment", "animated-map",
    )
    return cycle[(idx - 1) % len(cycle)]


def _beat_asset_type(parent_type: str, beat_index: int) -> str:
    if beat_index == 1:
        return parent_type
    alternates = {
        "cinematic-reenactment": ("atmospheric-detail", "archival-footage", "evidence-board"),
        "archival-portrait": ("newspaper-document", "cinematic-reenactment"),
        "newspaper-document": ("evidence-board", "archival-footage"),
        "animated-map": ("location-card", "cinematic-reenactment"),
        "date-card": ("archival-footage", "newspaper-document"),
    }
    choices = alternates.get(parent_type, ("cinematic-reenactment", "atmospheric-detail"))
    return choices[(beat_index - 2) % len(choices)]
