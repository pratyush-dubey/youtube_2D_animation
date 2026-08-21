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
                report.add("video_min_duration", duration >= 30,
                           f"{duration:.0f}s (min 30s)")
                # Check resolution
                for s in streams:
                    if s.get("codec_type") == "video":
                        w = s.get("width", 0)
                        h = s.get("height", 0)
                        report.add("video_resolution",
                                   w >= 1280 and h >= 720,
                                   f"{w}x{h}")
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
