"""The product-level AI Video Director.

This is the only orchestration API the default user experience calls.  The
specialized directors below adapt existing agents and local tools; they are not
separate user workflows.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import AgentContext, AgentResult
from app.config.settings import settings

logger = structlog.get_logger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class VideoRequest:
    request: str
    duration_seconds: int = 60
    language: str = "English"
    style: str = "Cinematic Documentary"
    aspect_ratio: str = "16:9"

    @classmethod
    def from_natural_language(
        cls, request: str, duration_seconds: int | None = None,
        language: str | None = None, style: str | None = None,
    ) -> VideoRequest:
        """Apply safe, deterministic hints while selectors remain authoritative."""
        text = request.strip()
        inferred_duration = duration_seconds or 60
        match = re.search(r"\b(\d+)\s*[- ]?(minute|min|second|sec)s?\b", text, re.I)
        if match and duration_seconds is None:
            value = int(match.group(1))
            inferred_duration = value * 60 if match.group(2).lower().startswith("m") else value
        inferred_duration = min(max(inferred_duration, 30), 3600)
        inferred_style = style or (
            "Cinematic Documentary" if "documentary" in text.lower() else "Cinematic Story"
        )
        return cls(text, inferred_duration, language or "English", inferred_style)


@dataclass(frozen=True)
class GraphNode:
    name: str
    label: str
    dependencies: tuple[str, ...] = ()


class ProductionGraph:
    """Explicit, validated production dependencies."""

    nodes = (
        GraphNode("research", "Research"),
        GraphNode("story", "Story", ("research",)),
        GraphNode("script", "Script", ("story",)),
        GraphNode("characters", "Characters", ("script",)),
        GraphNode("visuals", "Visuals", ("characters",)),
        GraphNode("shots", "Shot Plan", ("visuals",)),
        GraphNode("animation", "Animation", ("shots",)),
        GraphNode("voice", "Voice", ("script", "shots")),
        GraphNode("sound", "Sound", ("shots",)),
        GraphNode("music", "Music", ("story",)),
        GraphNode("rendering", "Rendering", ("animation", "voice", "sound", "music")),
        GraphNode("subtitles", "Subtitles", ("rendering",)),
        GraphNode("thumbnail", "Thumbnail", ("rendering",)),
        GraphNode("seo", "SEO", ("rendering", "subtitles")),
        GraphNode("quality", "Quality Control", ("rendering", "subtitles", "thumbnail", "seo")),
        GraphNode("youtube", "YouTube", ("quality",)),
    )

    @classmethod
    def as_dict(cls) -> list[dict[str, Any]]:
        return [asdict(node) for node in cls.nodes]

    @classmethod
    def validate(cls) -> None:
        seen: set[str] = set()
        for node in cls.nodes:
            missing = set(node.dependencies) - seen
            if missing:
                raise ValueError(f"Invalid production graph: {node.name} precedes {sorted(missing)}")
            seen.add(node.name)


class SpecializedDirector:
    name = "specialized"

    def run(self, context: AgentContext) -> Any:
        raise NotImplementedError

    @staticmethod
    def require(result: AgentResult) -> Any:
        if not result.success:
            raise RuntimeError(result.error or f"{result.agent_name} failed")
        return result.output


class ResearchDirector(SpecializedDirector):
    name = "research"
    def __init__(self, llm): self.llm = llm
    def run(self, context):
        from app.agents.research_agent import ResearchAgent
        return self.require(ResearchAgent(llm=self.llm).run(context))


class StoryDirector(SpecializedDirector):
    name = "story"
    def run(self, context):
        facts = list(getattr(context.research, "facts", []) or [])
        brief = {
            "request": context.topic, "genre": context.style,
            "tone": "cinematic, factual, engaging",
            "structure": ["hook", "context", "rising action", "turning point", "legacy"],
            "research_anchors": [str(item) for item in facts[:12]],
        }
        (context.output_dir / "story_brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")
        return brief


class ScriptDirector(SpecializedDirector):
    name = "script"
    def __init__(self, llm): self.llm = llm
    def run(self, context):
        from app.agents.script_agent import ScriptAgent
        return self.require(ScriptAgent(llm=self.llm).run(context))


class CharacterDirector(SpecializedDirector):
    name = "characters"
    def __init__(self, llm): self.llm = llm
    def run(self, context):
        from app.agents.character_agent import CharacterAgent
        return self.require(CharacterAgent(llm=self.llm).run(context))


class VisualDirector(SpecializedDirector):
    name = "visuals"
    def __init__(self, llm): self.llm = llm
    def run(self, context):
        from app.agents.asset_agent import AssetAgent
        from app.agents.storyboard_agent import StoryboardAgent
        self.require(StoryboardAgent(llm=self.llm).run(context))
        return self.require(AssetAgent().run(context))


class ShotDirector(SpecializedDirector):
    name = "shots"
    def run(self, context):
        scenes = list(context.storyboard or [])
        if not scenes:
            raise RuntimeError("No scenes were produced")
        plan = {"scene_count": len(scenes), "scenes": scenes}
        (context.output_dir / "shot_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return plan


class AnimationDirector(SpecializedDirector):
    name = "animation"
    def run(self, context):
        weak = [s.get("scene_id") for s in context.storyboard or [] if not (s.get("shots") or s.get("animation_type"))]
        if weak:
            raise RuntimeError(f"Shots missing animation instructions: {weak}")
        return {"planned_shots": len(context.storyboard or []), "mode": settings.render_provider}


class SoundDirector(SpecializedDirector):
    name = "sound"
    def run(self, context):
        from app.agents.audio_director_agent import AudioDirectorAgent
        return self.require(AudioDirectorAgent().run(context))


class VoiceDirector(SpecializedDirector):
    name = "voice"
    def run(self, context):
        if not context.audio_plan:
            SoundDirector().run(context)
        from app.agents.voice_agent import VoiceAgent
        return self.require(VoiceAgent().run(context))


class MusicDirector(SpecializedDirector):
    name = "music"
    def run(self, context):
        from app.agents.music_agent import MusicAgent
        return self.require(MusicAgent().run(context))


class SubtitleDirector(SpecializedDirector):
    name = "subtitles"
    def run(self, context):
        srt = context.output_dir / "subtitles.srt"
        if not srt.is_file():
            raise RuntimeError("Subtitle generation did not produce an SRT file")
        vtt = context.output_dir / "subtitles.vtt"
        body = srt.read_text(encoding="utf-8-sig")
        vtt.write_text("WEBVTT\n\n" + body.replace(",", "."), encoding="utf-8")
        return {"srt": str(srt), "vtt": str(vtt)}


class _RenderingDirector(SpecializedDirector):
    name = "rendering"
    def run(self, context):
        from app.agents.video_edit_agent import VideoEditAgent
        return self.require(VideoEditAgent().run(context))


class ThumbnailDirector(SpecializedDirector):
    name = "thumbnail"
    def __init__(self, llm): self.llm = llm
    def run(self, context):
        from app.agents.thumbnail_agent import ThumbnailAgent
        return self.require(ThumbnailAgent(llm=self.llm).run(context))


class SEODirector(SpecializedDirector):
    name = "seo"
    def __init__(self, llm): self.llm = llm
    def run(self, context):
        from app.agents.seo_agent import SEOAgent
        return self.require(SEOAgent(llm=self.llm).run(context))


class QualityDirector(SpecializedDirector):
    name = "quality"
    def run(self, context):
        from app.agents.quality_agent import QualityAgent
        report = self.require(QualityAgent().run(context))
        passed = sum(1 for check in report.checks if check.get("passed"))
        score = round(100 * passed / max(len(report.checks), 1))
        data = {"passed": report.passed, "score": score, "minimum_score": settings.minimum_video_quality_score, "checks": report.checks}
        (context.output_dir / "quality_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        if not report.passed or score < settings.minimum_video_quality_score:
            raise QualityBelowThreshold(score, report.checks)
        return data


class QualityBelowThreshold(RuntimeError):
    def __init__(self, score: int, checks: list[dict]):
        self.score, self.checks = score, checks
        self.failed_checks = [c["check"] for c in checks if not c.get("passed")]
        super().__init__(f"Quality score {score}/100; failed checks: {', '.join(self.failed_checks)}")


class YouTubeDirector(SpecializedDirector):
    name = "youtube"
    def run(self, context):
        from app.agents.youtube_agent import YouTubeAgent
        return self.require(YouTubeAgent().run(context))


class Director:
    """Executes the whole graph and exposes only high-level production state."""

    state_filename = "director_state.json"

    def __init__(self, job_id: str, project_id: str, video_request: VideoRequest):
        ProductionGraph.validate()
        self.job_id, self.project_id, self.request = job_id, project_id, video_request
        self.output_dir = Path(settings.output_dir) / project_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output_dir / self.state_filename
        self.state = self._new_state()

    def _new_state(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "job_id": self.job_id,
            "request": asdict(self.request), "state": "QUEUED", "progress": 0,
            "quality_score": None, "requires_attention": False,
            "created_at": _now(), "updated_at": _now(), "revision": 0,
            "graph": ProductionGraph.as_dict(),
            "stages": {node.name: {"label": node.label, "status": "pending", "progress": 0, "attempts": 0, "message": None} for node in ProductionGraph.nodes},
        }

    @classmethod
    def read_state(cls, project_id: str) -> dict[str, Any] | None:
        path = Path(settings.output_dir) / project_id / cls.state_filename
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self) -> None:
        self.state["updated_at"] = _now()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)
        from app.api.job_store import job_store
        job_store.update(self.job_id, stage=self._active_stage(), progress=self.state["progress"], production_state=self.state["state"])

    def _active_stage(self) -> str | None:
        return next((name for name, item in self.state["stages"].items() if item["status"] == "running"), None)

    def _project_status(self, status: str) -> None:
        from app.database.models import Project
        from app.database.session import get_session
        with get_session() as session:
            row = session.query(Project).filter_by(id=self.project_id).first()
            if row:
                row.status = status.lower()

    def _directors(self, llm) -> dict[str, SpecializedDirector]:
        return {
            "research": ResearchDirector(llm), "story": StoryDirector(),
            "script": ScriptDirector(llm), "characters": CharacterDirector(llm),
            "visuals": VisualDirector(llm), "shots": ShotDirector(),
            "animation": AnimationDirector(), "voice": VoiceDirector(),
            "sound": SoundDirector(), "music": MusicDirector(),
            "rendering": _RenderingDirector(), "subtitles": SubtitleDirector(),
            "thumbnail": ThumbnailDirector(llm), "seo": SEODirector(llm),
            "quality": QualityDirector(),
        }

    def execute(self) -> dict[str, Any]:
        from app.api.job_store import job_store
        from app.llm.factory import get_llm_provider

        context = AgentContext(
            project_id=self.project_id, topic=self.request.request,
            language=self.request.language, style=self.request.style,
            target_duration_seconds=self.request.duration_seconds,
            aspect_ratio=self.request.aspect_ratio, output_dir=self.output_dir,
        )
        executable = [node for node in ProductionGraph.nodes if node.name != "youtube"]
        self.state["state"] = "PRODUCING"
        self._project_status("PRODUCING")
        self._save()
        try:
            try:
                llm = get_llm_provider()
            except (ValueError, RuntimeError) as exc:
                if not settings.zero_cost_mode or settings.llm_provider == "ollama":
                    raise
                logger.warning(
                    "director_llm_falling_back_to_ollama",
                    configured=settings.llm_provider,
                    reason=str(exc).splitlines()[0],
                )
                self.state["provider_fallback"] = {
                    "from": settings.llm_provider,
                    "to": "ollama",
                    "message": "Configured cloud provider is unavailable; using local Ollama.",
                }
                self._save()
                llm = get_llm_provider("ollama")
            workers = self._directors(llm)
            for index, node in enumerate(executable):
                self._run_stage(node, workers[node.name], context)
                self.state["progress"] = round((index + 1) * 100 / len(executable))
                self._save()
            self.state["stages"]["youtube"].update(
                status="waiting_approval", progress=0,
                message="Waiting for final human approval",
            )
            self.state["state"] = "VIDEO_READY"
            self.state["progress"] = 100
            self._project_status("VIDEO_READY")
            job_store.update(self.job_id, status="complete", stage=None, progress=100, finished_at=_now())
        except QualityBelowThreshold as exc:
            self.state["quality_score"] = exc.score
            self.state["state"] = "EDITOR_REVIEW"
            self.state["requires_attention"] = True
            self._project_status("EDITOR_REVIEW")
            job_store.update(self.job_id, status="requires_attention", error=self._friendly_error("quality", exc), finished_at=_now())
        except Exception as exc:
            stage = self._active_stage() or "production"
            self.state["state"] = "REQUIRES_ATTENTION"
            self.state["requires_attention"] = True
            self._project_status("REQUIRES_ATTENTION")
            job_store.update(self.job_id, status="requires_attention", error=self._friendly_error(stage, exc), finished_at=_now())
            logger.exception("director_failed", project=self.project_id, stage=stage)
        self._save()
        return self.state

    def _run_stage(self, node: GraphNode, worker: SpecializedDirector, context: AgentContext) -> None:
        item = self.state["stages"][node.name]
        for dependency in node.dependencies:
            if self.state["stages"][dependency]["status"] != "complete":
                raise RuntimeError(f"{node.label} is waiting for {dependency}")
        for attempt in range(1, settings.director_max_stage_retries + 2):
            item.update(status="running", progress=10, attempts=attempt, message=None)
            self._save()
            try:
                output = worker.run(context)
                item.update(status="complete", progress=100, message=None)
                if node.name == "quality" and isinstance(output, dict):
                    self.state["quality_score"] = output.get("score")
                return
            except Exception as exc:
                if attempt <= settings.director_max_stage_retries:
                    item.update(status="retrying", progress=35, message=self._friendly_error(node.name, exc))
                    self._save()
                    if isinstance(exc, QualityBelowThreshold):
                        self._auto_repair(exc, context)
                    time.sleep(min(settings.retry_backoff_base * attempt, 5))
                    continue
                item.update(status="failed", progress=100, message=self._friendly_error(node.name, exc))
                raise

    def _auto_repair(self, failure: QualityBelowThreshold, context: AgentContext) -> None:
        """Repair only implicated assets; never restart an otherwise valid production."""
        failed = set(failure.failed_checks)
        workers = self._directors(get_llm_provider_cached())

        visual_checks = {
            "all_scenes_have_images", "visual_prompt_relevance", "image_variety",
            "production_visual_mode", "illustrated_asset_quality",
            "character_identity_references", "animated_character_presence",
        }
        audio_checks = {"video_has_audio", "narration_files_exist"}
        render_checks = {"video_exists", "video_has_stream", "video_min_duration", "video_resolution", "video_probe"}

        if failed & visual_checks:
            # Remove only the scene assets explicitly named by QA details.
            affected: set[int] = set()
            for check in failure.checks:
                if not check.get("passed"):
                    affected.update(int(x) for x in re.findall(r"\b\d+\b", str(check.get("detail", ""))))
            for scene_id in affected:
                (self.output_dir / "images" / f"scene_{scene_id:03d}.jpg").unlink(missing_ok=True)
            manifest = self.output_dir / "images" / "manifest.json"
            if affected and manifest.is_file():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    for scene_id in affected:
                        data.pop(str(scene_id), None)
                    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
                except (OSError, ValueError):
                    pass
            workers["visuals"].run(context)

        if failed & audio_checks:
            workers["voice"].run(context)

        if failed & (render_checks | visual_checks | audio_checks):
            for name in ("final.mp4", "subtitled.mp4", "concat.mp4"):
                (self.output_dir / name).unlink(missing_ok=True)
            workers["rendering"].run(context)
            workers["subtitles"].run(context)

        if failed & {"seo_present", "seo_title", "seo_description", "seo_tags"}:
            workers["seo"].run(context)
        if "thumbnail_exists" in failed:
            (self.output_dir / "thumbnail.jpg").unlink(missing_ok=True)
            workers["thumbnail"].run(context)

    @staticmethod
    def _friendly_error(stage: str, exc: Exception) -> str:
        messages = {
            "characters": "Character generation temporarily unavailable.",
            "visuals": "Visual generation temporarily unavailable.",
            "voice": "Voice generation failed after automatic retries.",
            "rendering": "Rendering failed after automatic retries.",
            "quality": "Quality control needs editor review.",
        }
        return messages.get(stage, f"{stage.replace('_', ' ').title()} could not be completed automatically.")


def get_llm_provider_cached():
    """Late import keeps Director import cheap for API status requests."""
    from app.llm.factory import get_llm_provider
    return get_llm_provider()
