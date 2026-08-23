"""The product-level AI Video Director.

This is the only orchestration API the default user experience calls.  The
specialized directors below adapt existing agents and local tools; they are not
separate user workflows.
"""
from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import AgentContext, AgentResult, is_retryable_exception
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
        GraphNode("voice", "Narration", ("script",)),
        GraphNode("characters", "Characters", ("research",)),
        GraphNode("timeline", "Master Timeline", ("voice", "characters")),
        GraphNode("visuals", "Visuals", ("characters", "timeline")),
        GraphNode("shots", "Shot Plan", ("visuals", "timeline")),
        GraphNode("animation", "Animation", ("shots",)),
        GraphNode("sound", "Sound", ("shots", "timeline")),
        GraphNode("music", "Music", ("story", "timeline")),
        GraphNode("rendering", "Rendering", ("animation", "voice", "sound", "music")),
        GraphNode("subtitles", "Subtitles", ("rendering",)),
        GraphNode("seo", "SEO", ("rendering", "subtitles")),
        GraphNode("thumbnail", "Thumbnail", ("rendering", "seo")),
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
            if result.exception is not None:
                raise result.exception
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
    def __init__(self, llm, job_id: str = "visual-diagnostic"):
        self.llm = llm
        self.job_id = job_id
    def run(self, context):
        from app.agents.asset_agent import AssetAgent
        from app.agents.storyboard_agent import StoryboardAgent, _write_storyboard
        from app.image_generation.visual_stage import VisualStageLog, VisualTrace, write_failure_report, write_visual_exception

        audit = VisualStageLog(context.output_dir, context.project_id)
        trace = VisualTrace(context.output_dir, context.project_id)
        context.visual_trace = trace
        started = time.perf_counter()
        from app.api.job_runner import _job_trace
        _job_trace(context.project_id, "WORKER_ENTERED_VISUALS", self.job_id, worker_state="visuals")
        trace.mark(1)
        audit.emit("VISUALS_STARTED")
        try:
            trace.mark(2, output_dir=str(context.output_dir.resolve()))
            if context.script is None:
                raise RuntimeError("Visuals cannot start because the parsed script is missing")
            trace.mark(3, script_type=type(context.script).__name__)
            audit.emit("VISUALS_SCRIPT_PARSED")
            trace.mark(4, character_count=len((context.character_sheet or {}).get("characters", [])))
            trace.mark(5, operation="master_timeline_storyboard" if context.master_timeline else "StoryboardAgent.run")
            if not context.master_timeline:
                self.require(StoryboardAgent(llm=self.llm).run(context))
            audit.emit("VISUAL_SCENES_PLANNED", scene_count=len(context.storyboard or []))
            shot_count = sum(max(len(scene.get("shots") or []), 1) for scene in context.storyboard or [])
            trace.mark(6, scene_count=len(context.storyboard or []), shot_count=shot_count)
            audit.emit("VISUAL_PROMPTS_CREATED", scene_count=len(context.storyboard or []))
            trace.mark(7, prompt_count=len(context.storyboard or []))
            trace.mark(8, provider=settings.image_provider)
            output = self.require(AssetAgent().run(context))
            # Asset preparation enriches each scene with quality reports,
            # resolved layers and character bindings. Persist those additions
            # so a later stage-only retry hydrates the same validated scene
            # data instead of treating the reports as missing.
            _write_storyboard(
                context.output_dir / "storyboard.json",
                context.storyboard,
                context.script,
            )
            trace.mark(19, asset_count=len(output))
            audit.emit("VISUALS_COMPLETED", duration=time.perf_counter() - started, asset_count=len(output))
            return output
        except Exception as exc:
            write_visual_exception(context.output_dir, context.project_id, exc)
            failure_path = context.output_dir / "reports" / "visual_failure.json"
            if not failure_path.is_file():
                provider_name = getattr(self.llm, "provider_name", "unknown")
                write_failure_report(context.output_dir, exc, provider=f"llm_{provider_name}")
            audit.emit("VISUALS_FAILED", duration=time.perf_counter() - started, error=f"{type(exc).__name__}: {exc}")
            raise


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
        from app.agents.voice_agent import VoiceAgent
        return self.require(VoiceAgent().run(context))


class TimelineDirector(SpecializedDirector):
    name = "timeline"

    def run(self, context):
        from app.timeline.master import build_master_timeline
        if not context.narration_alignment:
            raise RuntimeError("Measured narration alignment is required before timeline planning")
        # Use the real person CharacterAgent identified (its name is the exact
        # key app.agents.asset_agent._attach_character_assets matches against
        # to wire up character_rig_manifest) instead of a topic-derived slug -
        # otherwise no scene's character_name ever matches a character-sheet
        # entry and the renderer never finds a rig to animate.
        primary_character = next(
            (
                str(c.get("name", "")).strip()
                for c in (context.character_sheet or {}).get("characters", [])
                if str(c.get("name", "")).strip()
            ),
            "",
        )
        character_id = primary_character or re.sub(
            r"[^a-z0-9]+", "_", (context.chosen_topic or context.topic).lower()
        ).strip("_")
        # "context-specific documentary reconstruction" used to be a literal,
        # unfilled placeholder here for every single scene - it gave the image
        # generator nothing concrete to draw, so every background regressed to
        # a generic moody-forest default regardless of the actual topic. Each
        # narration sentence already describes what's happening in that beat;
        # ground the environment/image prompt in it (plus the topic) instead.
        topic_label = str(context.chosen_topic or context.topic).strip()
        sources = [
            {
                "text": item["text"], "audio_path": item["audio_path"],
                "character_id": character_id,
                "environment": f"{topic_label}: {' '.join(str(item['text']).split())[:180]}",
                "visual_type": "ai_reconstruction",
                "section_id": item.get("section_id"), "section_title": item.get("section_title"),
                "section_narration": item.get("section_narration"),
                "emotion": item.get("voice_emotion"), "music": item.get("music_mood"),
            }
            for item in context.narration_alignment
        ]
        timeline = build_master_timeline(
            sources, character_id=character_id,
            output_path=context.output_dir / "timeline.json",
        )
        context.master_timeline = timeline
        # Group consecutive shots that belong to the same script section into
        # one scene sharing a single illustrated background instead of giving
        # every narration sentence its own brand-new illustration and its own
        # independently-rendered clip. That one-illustration-per-sentence
        # default was the actual mechanism behind the "slideshow" look: a hard
        # cut to a fresh painting every 2-8 seconds regardless of whether the
        # story had even changed location. Shots inside a group keep their own
        # camera/action/framing as sub-shots (the renderer already selects the
        # active sub-shot by elapsed time - see _active_shot in
        # app/video/animated_renderer.py) so continuity of place doesn't come
        # at the cost of continuity of blocking.
        groups: list[list[dict]] = []
        for shot in timeline["shots"]:
            key = shot.get("section_id") or shot["shot_id"]
            if groups and (groups[-1][0].get("section_id") or groups[-1][0]["shot_id"]) == key:
                groups[-1].append(shot)
            else:
                groups.append([shot])
        scenes = []
        for index, group in enumerate(groups, 1):
            lead = group[0]
            scene_environment = str(lead.get("section_title") or lead["environment"])
            scene_subject = str(lead.get("section_narration") or lead["environment"])
            scene_start = float(lead["start"])
            cumulative = 0.0
            sub_shots = []
            character_actions = []
            for shot in group:
                action = shot["action"]
                character_actions.append(action)
                camera_move = {
                    "tracking": "track_character", "follow": "follow_character",
                    "subtle_orbit": "orbit_simulation", "dolly": "dolly_in",
                    "settle": "handheld", "locked_medium": "static", "locked": "static",
                }.get(shot["camera"]["move"], "slow_push")
                sub_shots.append({
                    "id": shot["shot_id"], "start": round(cumulative, 3), "duration": shot["duration"],
                    "shot_type": shot["framing"], "camera": camera_move,
                    "characters": shot["characters"], "action": action,
                    "expression": shot["emotion"], "subject": shot["environment"],
                    "transition": "cut", "master_start": shot["start"],
                    "master_end": shot["end"],
                    "character_position": shot.get("character_position"),
                })
                cumulative += float(shot["duration"])
            duration_seconds = round(cumulative, 3)
            primary_action = character_actions[0]
            scenes.append({
                "scene_id": index, "duration_seconds": duration_seconds,
                "narration": " ".join(shot["narration_segment"]["text"] for shot in group),
                "visual_description": f"{scene_subject}; {character_id} performs {primary_action}",
                "image_prompt": f"AI reconstruction, {scene_subject}, full-body {character_id}, action-ready composition, no text",
                "visual_type": lead["visual_type"], "still_image_shot": lead["still_image_shot"],
                # AssetAgent._prepare_scene_asset only attaches character_rig_manifest
                # (and runs the asset quality gate) for DRAFT/PRODUCTION scenes; a
                # scene with no visual_quality silently skips rig attachment.
                "visual_quality": settings.visual_quality,
                "character_name": character_id, "character_action": primary_action,
                "character_motion": primary_action, "character_is_fictional": False,
                "environment": scene_environment, "emotion": lead["emotion"],
                "voice_emotion": lead["emotion"], "music_mood": lead["music"],
                "sfx": sorted({sfx for shot in group for sfx in shot["sound_effects"]}),
                "asset_type": "cinematic-reenactment",
                "sfx_events": [
                    {**event, "local_start": round(float(event["start"]) - scene_start, 3)}
                    for shot in group for event in timeline["tracks"]["sfx"]
                    if event.get("shot_id") == shot["shot_id"]
                ],
                "shots": sub_shots,
            })
        context.storyboard = scenes
        storyboard = {
            "storyboard_version": 5, "clock": "measured_narration_seconds",
            "total_scenes": len(scenes), "total_duration_seconds": timeline["duration"],
            "scenes": scenes,
        }
        (context.output_dir / "storyboard.json").write_text(json.dumps(storyboard, indent=2), encoding="utf-8")
        (context.output_dir / "shot_manifest.json").write_text(
            json.dumps({"schema_version": "2.0", "shots": timeline["shots"]}, indent=2), encoding="utf-8",
        )
        return timeline


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

    def __init__(
        self, job_id: str, project_id: str, video_request: VideoRequest,
        resume_stage: str | None = None,
    ):
        ProductionGraph.validate()
        self.job_id, self.project_id, self.request = job_id, project_id, video_request
        self.resume_stage = resume_stage
        self.output_dir = Path(settings.output_dir) / project_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output_dir / self.state_filename
        persisted = self.read_state(project_id) if resume_stage else None
        self.state = persisted or self._new_state()
        self.state["job_id"] = job_id
        self.state["graph"] = ProductionGraph.as_dict()
        for node in ProductionGraph.nodes:
            self.state.setdefault("stages", {}).setdefault(
                node.name,
                {"label": node.label, "status": "pending", "progress": 0, "attempts": 0, "message": None},
            )
        # A stage that later completed must not keep an obsolete error from an
        # earlier retry; otherwise the UI reports failure and success together.
        for stage in self.state.get("stages", {}).values():
            if stage.get("status") == "complete":
                stage.pop("error", None)
                stage.pop("error_type", None)
                stage["message"] = None

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
        if self.state_path.is_file():
            try:
                persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
                if persisted.get("watchdog_failure") and self.state.get("state") != "VISUALS_FAILED":
                    self.state = persisted
                    return
            except (OSError, ValueError):
                pass
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
            "script": ScriptDirector(llm), "voice": VoiceDirector(),
            "timeline": TimelineDirector(), "characters": CharacterDirector(llm),
            "visuals": VisualDirector(llm, self.job_id), "shots": ShotDirector(),
            "animation": AnimationDirector(),
            "sound": SoundDirector(), "music": MusicDirector(),
            "rendering": _RenderingDirector(), "subtitles": SubtitleDirector(),
            "thumbnail": ThumbnailDirector(llm), "seo": SEODirector(llm),
            "quality": QualityDirector(),
        }

    def _hydrate_context(self, context: AgentContext) -> None:
        """Restore completed stage outputs without invoking their workers again."""
        from app.research.schemas import ResearchResult
        from app.script.schemas import ScriptResult
        from app.seo.schemas import SEOMetadata

        loaders = (
            ("research.json", "research", ResearchResult),
            ("script.json", "script", ScriptResult),
            ("seo.json", "seo", SEOMetadata),
        )
        for filename, attribute, model in loaders:
            path = self.output_dir / filename
            if path.is_file():
                try:
                    setattr(context, attribute, model.model_validate_json(path.read_text(encoding="utf-8")))
                except (ValueError, OSError):
                    pass

        for filename, attribute, key in (
            ("characters.json", "character_sheet", None),
            ("storyboard.json", "storyboard", "scenes"),
            ("audio/audio_plan.json", "audio_plan", None),
        ):
            path = self.output_dir / filename
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    setattr(context, attribute, value.get(key, []) if key else value)
                except (ValueError, OSError):
                    pass

        for filename, attribute, key in (
            ("timeline.json", "master_timeline", None),
            ("narration_alignment.json", "narration_alignment", "segments"),
        ):
            path = self.output_dir / filename
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    setattr(context, attribute, value.get(key, []) if key else value)
                except (ValueError, OSError):
                    pass

        images_dir = self.output_dir / "images"
        context.images = {
            int(match.group(1)): path
            for path in images_dir.glob("scene_*.jpg")
            if (match := re.match(r"scene_(\d+)\.jpg$", path.name))
        }
        narration_dir = self.output_dir / "audio" / "narration"
        context.narration_files = {
            int(match.group(1)): path
            for path in narration_dir.glob("scene_*.*")
            if (match := re.match(r"scene_(\d+)\.(?:wav|mp3)$", path.name))
        }
        for candidate in (self.output_dir / "final.mp4", self.output_dir / "subtitled.mp4"):
            if candidate.is_file():
                context.video_path = candidate
                break
        thumbnail = self.output_dir / "thumbnail.jpg"
        if thumbnail.is_file():
            context.thumbnail_path = thumbnail

    def execute(self) -> dict[str, Any]:
        from app.api.job_store import job_store
        from app.llm.factory import get_llm_provider

        context = AgentContext(
            project_id=self.project_id, topic=self.request.request,
            language=self.request.language, style=self.request.style,
            target_duration_seconds=self.request.duration_seconds,
            aspect_ratio=self.request.aspect_ratio, output_dir=self.output_dir,
        )
        self._hydrate_context(context)
        executable = [node for node in ProductionGraph.nodes if node.name != "youtube"]
        start_index = 0
        if self.resume_stage:
            names = [node.name for node in executable]
            if self.resume_stage not in names:
                raise ValueError(f"Unknown retry stage: {self.resume_stage}")
            start_index = names.index(self.resume_stage)
            node_by_name = {node.name: node for node in executable}

            def include_incomplete_dependencies(stage_name: str) -> None:
                nonlocal start_index
                for dependency in node_by_name[stage_name].dependencies:
                    if self.state["stages"][dependency]["status"] != "complete":
                        start_index = min(start_index, names.index(dependency))
                        include_incomplete_dependencies(dependency)

            include_incomplete_dependencies(self.resume_stage)
            self.state["stages"][self.resume_stage].update(
                status="pending", progress=0, message=None,
            )
            self.state["requires_attention"] = False
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
            for index in range(start_index, len(executable)):
                node = executable[index]
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
            stage = self._active_stage() or next(
                (name for name, value in self.state["stages"].items() if value["status"] == "failed"),
                "production",
            )
            self.state["state"] = "VISUALS_FAILED" if stage == "visuals" else "REQUIRES_ATTENTION"
            self.state["requires_attention"] = True
            self._project_status(self.state["state"])
            job_store.update(self.job_id, status="requires_attention", error=self._friendly_error(stage, exc), finished_at=_now())
            logger.exception("director_failed", project=self.project_id, stage=stage)
        self._save()
        return self.state

    def _run_stage(self, node: GraphNode, worker: SpecializedDirector, context: AgentContext) -> None:
        item = self.state["stages"][node.name]
        for dependency in node.dependencies:
            if self.state["stages"][dependency]["status"] != "complete":
                raise RuntimeError(f"{node.label} is waiting for {dependency}")
        maximum_attempts = 1 if node.name == "visuals" else settings.director_max_stage_retries + 1
        for attempt in range(1, maximum_attempts + 1):
            item.update(status="running", progress=0, attempts=attempt, message=None)
            item.pop("error", None)
            item.pop("error_type", None)
            if node.name == "visuals":
                self.state["state"] = "VISUALS_RUNNING"

                def visual_progress(update: dict[str, Any]) -> None:
                    completed = int(update.get("completed", 0))
                    total = max(int(update.get("total", 0)), 1)
                    executable_count = len([entry for entry in ProductionGraph.nodes if entry.name != "youtube"])
                    visual_index = next(
                        index for index, entry in enumerate(ProductionGraph.nodes)
                        if entry.name == "visuals"
                    )
                    self.state["progress"] = round(
                        (visual_index + completed / total) * 100 / executable_count,
                        1,
                    )
                    item.update(
                        progress=round(completed * 100 / total, 1),
                        completed=completed,
                        total=total,
                        scene_id=update.get("scene_id"),
                        shot_id=update.get("shot_id"),
                        message=update.get("message"),
                    )
                    self._save()
                    if context.visual_trace:
                        context.visual_trace.mark(
                            18, scene_id=update.get("scene_id"), shot_id=update.get("shot_id"),
                            completed=completed, total=total, state="VISUALS_RUNNING",
                        )

                context.progress_callback = visual_progress
            self._save()
            try:
                output = worker.run(context)
                item.update(status="complete", progress=100, message=None)
                item.pop("error", None)
                item.pop("error_type", None)
                if node.name == "visuals":
                    self.state["state"] = "PRODUCING"
                    context.progress_callback = None
                if node.name == "quality" and isinstance(output, dict):
                    self.state["quality_score"] = output.get("score")
                return
            except Exception as exc:
                if attempt < maximum_attempts and is_retryable_exception(exc):
                    item.update(status="retrying", progress=35, message=self._friendly_error(node.name, exc))
                    self._save()
                    if isinstance(exc, QualityBelowThreshold):
                        self._auto_repair(exc, context)
                    time.sleep(min(settings.retry_backoff_base * attempt, 5))
                    continue
                item.update(status="failed", message=self._friendly_error(node.name, exc), error_type=type(exc).__name__, error=str(exc))
                self._write_stage_failure(node.name, exc, item)
                if node.name == "visuals":
                    self.state["state"] = "VISUALS_FAILED"
                    context.progress_callback = None
                raise

    def _write_stage_failure(self, stage: str, exc: Exception, item: dict[str, Any]) -> None:
        """Persist the exact exception and cause chain for every production stage."""
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
        final = frames[-1] if frames else None
        chain = []
        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            chain.append({"type": type(current).__name__, "message": str(current)})
            current = current.__cause__ or current.__context__
        payload = {
            "project_id": self.project_id, "job_id": self.job_id,
            "stage": stage, "status": "failed",
            "exception_type": type(exc).__name__, "exception_message": str(exc),
            "exception_chain": chain, "traceback": tb,
            "file": final.filename if final else None,
            "line": final.lineno if final else None,
            "attempts": item.get("attempts"), "timestamp": _now(),
        }
        reports = self.output_dir / "reports"
        logs = self.output_dir / "logs"
        reports.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        (reports / f"{stage}_failure.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        (logs / f"{stage}_exception.log").write_text(tb, encoding="utf-8")

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
            "visuals": f"{type(exc).__name__}: {exc}",
            "voice": "Voice generation failed after automatic retries.",
            "rendering": "Rendering failed after automatic retries.",
            "quality": "Quality control needs editor review.",
        }
        if stage in {"research", "story", "script", "characters", "visuals", "shots"}:
            return f"{type(exc).__name__}: {exc}"
        return messages.get(stage, f"{stage.replace('_', ' ').title()} could not be completed automatically.")


def get_llm_provider_cached():
    """Late import keeps Director import cheap for API status requests."""
    from app.llm.factory import get_llm_provider
    return get_llm_provider()
