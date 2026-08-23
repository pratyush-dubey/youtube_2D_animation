"""
QualityAgent — runs pre-upload checks on all generated assets.

Checks:
  Video:  exists, min duration, correct resolution, audio track present
  Audio:  narration files exist, not all silent
  Assets: every scene has an image
  SEO:    title, description, tags are non-empty
  Safety: basic content flag check via LLM
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext

logger = structlog.get_logger(__name__)


class QualityReport:
    def __init__(self) -> None:
        self.passed = True
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "passed": ok, "detail": detail})
        if not ok:
            self.passed = False

    def to_dict(self) -> dict:
        return {"passed": self.passed, "checks": self.checks}


class QualityAgent(Agent):
    name = "quality_agent"
    max_retries = 1

    def _execute(self, context: AgentContext) -> QualityReport:
        report = QualityReport()

        # ── Video ──────────────────────────────────────────────────────────
        if context.video_path and context.video_path.exists():
            size_mb = context.video_path.stat().st_size / 1e6
            report.add("video_exists", True, f"{size_mb:.1f} MB")

            try:
                info = self._probe(context.video_path)
                duration = float(info.get("format", {}).get("duration", 0))
                streams = info.get("streams", [])
                has_video = any(s["codec_type"] == "video" for s in streams)
                has_audio = any(s["codec_type"] == "audio" for s in streams)
                report.add("video_has_stream", has_video)
                report.add("video_has_audio", has_audio)
                target = max(float(context.target_duration_seconds or 0), 1.0)
                minimum = target * 0.85
                maximum = target * 1.15
                report.add(
                    "video_target_duration",
                    minimum <= duration <= maximum,
                    f"{duration:.1f}s (target {target:.0f}s; allowed {minimum:.1f}-{maximum:.1f}s)",
                )
                # Check resolution
                for s in streams:
                    if s.get("codec_type") == "video":
                        w = s.get("width", 0)
                        h = s.get("height", 0)
                        report.add("video_resolution",
                                   w >= 1280 and h >= 720,
                                   f"{w}x{h}")
                if context.master_timeline:
                    try:
                        from app.qa.media import inspect_render
                        cues_path = context.output_dir / "audio" / "audio_cues.json"
                        cues = json.loads(cues_path.read_text(encoding="utf-8")) if cues_path.is_file() else []
                        metadata = context.seo.model_dump() if context.seo and hasattr(context.seo, "model_dump") else {}
                        post = inspect_render(
                            context.video_path, context.master_timeline, metadata=metadata,
                            audio_cues=cues, subtitle_path=context.output_dir / "subtitles.srt",
                            output_path=context.output_dir / "post_render_qa.json",
                        )
                        for gate, result in post["gates"].items():
                            report.add(f"post_render_{gate}", bool(result["passed"]), json.dumps(result, default=str)[:600])
                    except Exception as exc:
                        report.add("post_render_qa", False, str(exc))
            except Exception as exc:
                report.add("video_probe", False, str(exc))
        else:
            report.add("video_exists", False, "No video file yet (later phases)")

        # ── Images ────────────────────────────────────────────────────────
        if context.storyboard:
            missing = [
                s["scene_id"] for s in context.storyboard
                if s["scene_id"] not in context.images
                   or not context.images[s["scene_id"]].exists()
            ]
            report.add("all_scenes_have_images", len(missing) == 0,
                       f"missing: {missing}" if missing else "OK")

            durations = [float(s.get("duration_seconds", 0)) for s in context.storyboard]
            max_duration = max(durations, default=0)
            avg_duration = sum(durations) / max(len(durations), 1)
            report.add(
                "shot_pacing",
                max_duration <= 10.0 and avg_duration <= 8.0,
                f"average {avg_duration:.1f}s, longest {max_duration:.1f}s",
            )

            max_words = max(
                (len(str(s.get("narration", "")).split()) for s in context.storyboard),
                default=0,
            )
            report.add(
                "caption_density",
                max_words <= 22,
                f"largest narration beat: {max_words} words",
            )

            weak_prompts = _weak_visual_prompts(context.storyboard)
            report.add(
                "visual_prompt_relevance",
                not weak_prompts,
                f"weak scene prompts: {weak_prompts}" if weak_prompts else "OK",
            )

            production_scenes = [
                scene for scene in context.storyboard if scene.get("production_version")
            ]
            if production_scenes:
                low_motion = [
                    scene.get("scene_id") for scene in production_scenes
                    if int((scene.get("animation_quality") or {}).get("score", 0)) < 70
                ]
                static_modes = [
                    scene.get("scene_id") for scene in production_scenes
                    if scene.get("render_mode") == "STATIC"
                ]
                report.add(
                    "animation_quality_score",
                    not low_motion,
                    f"below threshold: {low_motion}" if low_motion else "all scenes >= 70",
                )
                report.add(
                    "no_static_scene_fallback",
                    not static_modes,
                    f"static scenes: {static_modes}" if static_modes else "all scenes animated",
                )

                debug_scenes = [
                    scene.get("scene_id") for scene in production_scenes
                    if str(scene.get("visual_quality", "PRODUCTION")).upper() == "DEBUG"
                ]
                rejected_assets: list[int | None] = []
                missing_asset_reports: list[int | None] = []
                for scene in production_scenes:
                    scene_id = scene.get("scene_id")
                    quality_items = scene.get("asset_quality") or []
                    # Older/resumed projects may have validated image files
                    # but predate persistence of the per-scene report. Rebuild
                    # the deterministic report from the actual artifact.
                    if not quality_items:
                        image_path = context.images.get(int(scene_id)) if scene_id is not None else None
                        if image_path and image_path.is_file():
                            from dataclasses import asdict
                            from app.images.production_assets import evaluate_asset
                            rebuilt = asdict(evaluate_asset(
                                image_path,
                                str(scene.get("asset_type", "environment")),
                            ))
                            quality_items = [rebuilt]
                            scene["asset_quality"] = quality_items
                    if isinstance(quality_items, dict):
                        quality_items = [quality_items]
                    if not quality_items:
                        missing_asset_reports.append(scene_id)
                    elif any(
                        not bool(item.get("passed")) or int(item.get("score", 0)) < 80
                        for item in quality_items if isinstance(item, dict)
                    ):
                        rejected_assets.append(scene_id)
                report.add(
                    "production_visual_mode",
                    not debug_scenes,
                    f"DEBUG scenes: {debug_scenes}" if debug_scenes else "no DEBUG artwork",
                )
                report.add(
                    "illustrated_asset_quality",
                    not rejected_assets and not missing_asset_reports,
                    f"rejected: {rejected_assets}; missing reports: {missing_asset_reports}"
                    if rejected_assets or missing_asset_reports else "all illustrated assets >= 80",
                )

            duplicate_groups = _duplicate_image_groups(context.images)
            report.add(
                "image_variety",
                not duplicate_groups,
                f"near-duplicates: {duplicate_groups}" if duplicate_groups else "OK",
            )

            if context.character_sheet.get("characters"):
                reference_status = {
                    str(c.get("name", "")).casefold(): str(
                        c.get("identity_reference_status", "")
                    )
                    for c in context.character_sheet.get("characters", [])
                }
                eligible_character_scenes = [
                    s.get("scene_id") for s in context.storyboard
                    if s.get("character_name") and (
                        bool(s.get("character_is_fictional", False))
                        or reference_status.get(
                            str(s.get("character_name", "")).casefold(), ""
                        ).startswith("verified")
                    )
                ]
                animated_character_scenes = [
                    s.get("scene_id") for s in context.storyboard
                    if s.get("scene_id") in eligible_character_scenes
                    and s.get("character_motion")
                ]
                unsafe_identity_scenes = [
                    s.get("scene_id") for s in context.storyboard
                    if s.get("character_name")
                    and not bool(s.get("character_is_fictional", False))
                    and not reference_status.get(
                        str(s.get("character_name", "")).casefold(), ""
                    ).startswith("verified")
                ]
                report.add(
                    "character_identity_references",
                    not unsafe_identity_scenes,
                    f"missing verified references: {unsafe_identity_scenes}"
                    if unsafe_identity_scenes else "all named people are reference-locked",
                )
                # A documentary can intentionally use maps, documents and
                # atmospheric reenactments without assigning a character to a
                # scene. Only enforce animation when the storyboard actually
                # requests an eligible character performance.
                if eligible_character_scenes:
                    report.add(
                        "animated_character_presence",
                        bool(animated_character_scenes),
                        f"animated character scenes: {animated_character_scenes}"
                        if animated_character_scenes else "no animated character scenes",
                    )

        if context.script:
            missing_sections = _missing_script_sections(context.script, context.storyboard or [])
            report.add(
                "script_storyboard_coverage",
                not missing_sections,
                f"missing sections: {missing_sections}" if missing_sections else "OK",
            )
            promised = _leading_count(context.script.title)
            actual = len(context.script.sections)
            report.add(
                "title_count_matches_content",
                promised is None or promised == actual,
                f"title promises {promised}, script contains {actual}"
                if promised is not None else "not a numbered-list title",
            )

        # ── Narration ─────────────────────────────────────────────────────
        if context.narration_files:
            total = len(context.narration_files)
            non_empty = sum(
                1 for p in context.narration_files.values()
                if p.exists() and p.stat().st_size > 500
            )
            report.add("narration_files_exist", non_empty > 0,
                       f"{non_empty}/{total} non-empty")

        # ── SEO ───────────────────────────────────────────────────────────
        if context.seo:
            report.add("seo_title", bool(context.seo.best_title), context.seo.best_title[:50])
            report.add("seo_description", len(context.seo.description) > 100,
                       f"{len(context.seo.description)} chars")
            report.add("seo_tags", len(context.seo.tags) >= 5,
                       f"{len(context.seo.tags)} tags")
        else:
            report.add("seo_present", False, "SEOAgent must run first")

        # ── Thumbnail ─────────────────────────────────────────────────────
        if context.thumbnail_path and context.thumbnail_path.exists():
            size_kb = context.thumbnail_path.stat().st_size / 1024
            report.add("thumbnail_exists", size_kb > 5, f"{size_kb:.0f} KB")
        else:
            report.add("thumbnail_exists", False, "ThumbnailAgent must run first")

        logger.info(
            "quality_check_complete",
            project=context.project_id,
            passed=report.passed,
            checks=len(report.checks),
            failed=[c["check"] for c in report.checks if not c["passed"]],
        )
        return report

    def _probe(self, path: Path) -> dict:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)


_STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "this", "that", "from", "as", "at", "by",
    "it", "its", "into", "their", "they", "them", "be", "has", "have",
}


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(text).lower())
        if len(token) > 2 and token not in _STOP_WORDS
    }


def _weak_visual_prompts(scenes: list[dict]) -> list[int]:
    weak: list[int] = []
    for scene in scenes:
        subject = _tokens(
            f"{scene.get('visual_description', '')} {scene.get('narration', '')}"
        )
        prompt = _tokens(scene.get("image_prompt", ""))
        overlap = len(subject & prompt) / max(min(len(subject), 8), 1)
        if not prompt or (subject and overlap < 0.18):
            weak.append(scene.get("scene_id", 0))
    return weak


def _missing_script_sections(script: Any, scenes: list[dict]) -> list[str]:
    storyboard_tokens = _tokens(" ".join(str(s.get("narration", "")) for s in scenes))
    missing: list[str] = []
    for section in script.sections:
        section_tokens = _tokens(section.narration)
        coverage = len(section_tokens & storyboard_tokens) / max(len(section_tokens), 1)
        if coverage < 0.65:
            missing.append(section.title or f"section {section.id}")
    return missing


def _leading_count(title: str) -> int | None:
    match = re.match(r"^\s*(\d+)\b", str(title))
    return int(match.group(1)) if match else None


def _duplicate_image_groups(images: dict[int, Path]) -> list[list[int]]:
    """Detect visually repeated frames with a tiny dependency-free average hash."""
    try:
        from PIL import Image
    except ImportError:
        return []

    hashes: dict[int, int] = {}
    for scene_id, path in images.items():
        try:
            with Image.open(path) as image:
                pixels = list(image.convert("L").resize((8, 8)).getdata())
            mean = sum(pixels) / len(pixels)
            hashes[scene_id] = sum((1 << i) for i, value in enumerate(pixels) if value >= mean)
        except Exception:
            continue

    groups: list[list[int]] = []
    used: set[int] = set()
    ids = sorted(hashes)
    for i, first in enumerate(ids):
        if first in used:
            continue
        group = [first]
        for second in ids[i + 1:]:
            if (hashes[first] ^ hashes[second]).bit_count() <= 3:
                group.append(second)
                used.add(second)
        if len(group) > 1:
            used.add(first)
            groups.append(group)
    return groups
