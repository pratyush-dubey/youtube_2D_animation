"""
Pipeline orchestrator — Phase 1 + SEO + Thumbnail + YouTube.
Stages: research → script → seo → thumbnail → upload
"""
from __future__ import annotations

import traceback as tb
import uuid
from pathlib import Path
from typing import Any

import structlog

from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.database.models import Project
from app.database.session import get_session, init_db
from app.llm.factory import get_llm_provider
from app.pipeline.state import PipelineState
from app.research.researcher import Researcher
from app.script.script_generator import ScriptGenerator

logger = structlog.get_logger(__name__)


class PipelineResult:
    """Returned at the end of pipeline.run()."""

    def __init__(self, project_id: str, status: str, topic: str, output_dir: Path) -> None:
        self.project_id = project_id
        self.status = status
        self.topic = topic
        self.output_dir = output_dir
        self.script_title: str | None = None
        self.script_sections: int = 0
        self.estimated_duration_seconds: int = 0
        self.estimated_cost_usd: float = 0.0
        self.errors: list[str] = []
        # SEO
        self.seo_title: str | None = None
        self.seo_description: str | None = None
        self.seo_tags: list[str] = []
        self.seo_hashtags: list[str] = []
        self.seo_chapters: list[dict] = []
        # Thumbnail
        self.thumbnail_path: Path | None = None
        # YouTube
        self.youtube_video_id: str | None = None
        self.youtube_url: str | None = None
        self.youtube_privacy_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "status": self.status,
            "topic": self.topic,
            "output_dir": str(self.output_dir),
            "script_title": self.script_title,
            "script_sections": self.script_sections,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "estimated_cost_usd": self.estimated_cost_usd,
            "errors": self.errors,
            "seo": {
                "title": self.seo_title,
                "description": self.seo_description,
                "tags": self.seo_tags,
                "hashtags": self.seo_hashtags,
                "chapters": self.seo_chapters,
            },
            "thumbnail": str(self.thumbnail_path) if self.thumbnail_path else None,
            "youtube": {
                "video_id": self.youtube_video_id,
                "url": self.youtube_url,
                "privacy_status": self.youtube_privacy_status,
            } if self.youtube_video_id else None,
        }


class Orchestrator:
    """
    Top-level pipeline runner.

    Stages wired so far (each is independently resumable):
      1. research
      2. script
      3. metadata  (SEO: title / description / tags / chapters)
      4. thumbnail
      5. upload    (YouTube — only if video file exists)
    """

    def __init__(self, llm_override: str | None = None) -> None:
        init_db()
        self.llm = get_llm_provider(llm_override)

    def run(
        self,
        topic: str,
        language: str = "English",
        target_duration_seconds: int = 480,
        style: str = "documentary",
        aspect_ratio: str = "16:9",
        project_id: str | None = None,
        upload_to_youtube: bool = False,
        video_path: Path | None = None,
    ) -> PipelineResult:
        """
        Execute the pipeline.

        Args:
            upload_to_youtube: Set True to attempt YouTube upload.
                               Requires YOUTUBE_CLIENT_ID/SECRET in .env.
            video_path: Path to rendered MP4 (required for upload).
                        Phases 3-5 will populate this automatically once implemented.
        """
        project_id = project_id or self._create_project(
            topic=topic, language=language,
            target_duration_seconds=target_duration_seconds,
            style=style, aspect_ratio=aspect_ratio,
        )

        output_dir = settings.output_dir / project_id
        output_dir.mkdir(parents=True, exist_ok=True)

        state = PipelineState(project_id)
        cost_tracker = CostTracker(project_id)
        result = PipelineResult(
            project_id=project_id, status="running",
            topic=topic, output_dir=output_dir,
        )

        logger.info("pipeline_started", project=project_id, topic=topic,
                    language=language, target_s=target_duration_seconds)

        # ── STEP 1: Research ──────────────────────────────────────────────
        research_result = self._run_stage(
            stage="research",
            state=state, result=result, cost_tracker=cost_tracker,
            run_fn=lambda: Researcher(project_id=project_id, llm=self.llm)
                            .run(topic=topic, language=language),
            output_fn=lambda r: {"facts": len(r.facts), "claims": len(r.claims)},
            resume_fn=lambda: _load_research(project_id, topic),
        )
        if result.status == "failed":
            return result

        # Save research JSON
        if research_result:
            (output_dir / "research.json").write_text(
                research_result.model_dump_json(indent=2), encoding="utf-8"
            )

        # ── STEP 2: Script ────────────────────────────────────────────────
        script_result = self._run_stage(
            stage="script",
            state=state, result=result, cost_tracker=cost_tracker,
            run_fn=lambda: ScriptGenerator(project_id=project_id, llm=self.llm).generate(
                topic=topic, research=research_result,
                target_duration_seconds=target_duration_seconds,
                language=language, style=style,
            ),
            output_fn=lambda r: {
                "title": r.title, "sections": len(r.sections),
                "duration_s": r.estimated_duration_seconds, "word_count": r.word_count,
            },
            resume_fn=lambda: _load_script(project_id),
        )
        if result.status == "failed":
            return result

        if script_result:
            result.script_title = script_result.title
            result.script_sections = len(script_result.sections)
            result.estimated_duration_seconds = script_result.estimated_duration_seconds
            (output_dir / "script.json").write_text(
                script_result.model_dump_json(indent=2), encoding="utf-8"
            )

        # ── STEP 3: SEO Metadata ──────────────────────────────────────────
        from app.seo.metadata_generator import SEOGenerator
        seo_result = self._run_soft_stage(
            stage="metadata",
            state=state, result=result, cost_tracker=cost_tracker,
            run_fn=lambda: SEOGenerator(project_id=project_id, llm=self.llm).generate(
                topic=topic, script=script_result,
                research=research_result, language=language, style=style,
            ),
            output_fn=lambda r: {
                "title": r.best_title, "tags": len(r.tags),
                "chapters": len(r.chapters),
            },
            resume_fn=lambda: _load_seo(project_id),
        )

        if seo_result:
            result.seo_title = seo_result.best_title
            result.seo_description = seo_result.description
            result.seo_tags = seo_result.tags
            result.seo_hashtags = seo_result.hashtags
            result.seo_chapters = [c.model_dump() for c in seo_result.chapters]
            (output_dir / "seo.json").write_text(
                seo_result.model_dump_json(indent=2), encoding="utf-8"
            )

        # ── STEP 4: Thumbnail ─────────────────────────────────────────────
        from app.thumbnail.generator import ThumbnailGenerator
        thumb_result = self._run_soft_stage(
            stage="thumbnail",
            state=state, result=result, cost_tracker=cost_tracker,
            run_fn=lambda: ThumbnailGenerator(project_id=project_id, llm=self.llm).generate(
                topic=topic, seo=seo_result,
                output_dir=output_dir, style=style,
            ),
            output_fn=lambda r: {"thumbnail": str(r)},
            resume_fn=lambda: (output_dir / "thumbnail.jpg")
                               if (output_dir / "thumbnail.jpg").exists() else None,
        )
        if thumb_result:
            result.thumbnail_path = thumb_result

        # ── STEP 5: YouTube upload ────────────────────────────────────────
        if upload_to_youtube and video_path and video_path.exists():
            if state.should_run("upload"):
                state.start("upload")
                try:
                    from app.youtube.uploader import YouTubeUploader
                    upload_res = YouTubeUploader(project_id=project_id).upload(
                        video_path=video_path,
                        metadata=seo_result,
                        thumbnail_path=result.thumbnail_path,
                    )
                    result.youtube_video_id = upload_res.video_id
                    result.youtube_url = upload_res.url
                    result.youtube_privacy_status = upload_res.privacy_status
                    state.complete("upload", output_data=upload_res.to_dict())
                    logger.info("upload_complete", project=project_id,
                                video_id=upload_res.video_id, url=upload_res.url)
                except Exception as exc:
                    _handle_stage_error("upload", exc, state, result)
                    result.estimated_cost_usd = cost_tracker.total()
                    return result
        elif upload_to_youtube and not video_path:
            logger.warning(
                "upload_skipped_no_video",
                project=project_id,
                note="Provide --video-path when upload is requested",
            )

        result.status = "complete"
        result.estimated_cost_usd = cost_tracker.total()
        logger.info("pipeline_complete", project=project_id,
                    cost_usd=result.estimated_cost_usd, status=result.status)
        return result

    # ── generic stage runners ──────────────────────────────────────────────

    def _run_stage(
        self,
        stage: str,
        state: PipelineState,
        result: PipelineResult,
        cost_tracker: CostTracker,
        run_fn,
        output_fn,
        resume_fn,
    ):
        """Fatal stage: failure sets result.status = 'failed' and stops pipeline."""
        if not state.should_run(stage):
            return resume_fn()

        state.start(stage)
        try:
            stage_result = run_fn()
            state.complete(stage, output_data=output_fn(stage_result))
            return stage_result
        except Exception as exc:
            _handle_stage_error(stage, exc, state, result)
            result.estimated_cost_usd = cost_tracker.total()
            return None

    def _run_soft_stage(
        self,
        stage: str,
        state: PipelineState,
        result: PipelineResult,
        cost_tracker: CostTracker,
        run_fn,
        output_fn,
        resume_fn,
    ):
        """Soft stage: failure is logged as a warning but does NOT abort the pipeline."""
        if not state.should_run(stage):
            return resume_fn()

        state.start(stage)
        try:
            stage_result = run_fn()
            state.complete(stage, output_data=output_fn(stage_result))
            return stage_result
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:200]}"
            state.fail(stage, err)
            result.errors.append(f"{stage} (non-fatal): {err}")
            logger.warning(f"{stage}_skipped", project=result.project_id, error=err)
            return None

    # ── project creation ───────────────────────────────────────────────────

    def _create_project(self, topic, language, target_duration_seconds, style, aspect_ratio) -> str:
        project_id = str(uuid.uuid4())[:8]
        with get_session() as session:
            session.add(Project(
                id=project_id, topic=topic, language=language,
                target_duration_seconds=target_duration_seconds,
                style=style, aspect_ratio=aspect_ratio, status="created",
            ))
        logger.info("project_created", project=project_id, topic=topic)
        return project_id


# ── stage error helper ─────────────────────────────────────────────────────────

def _handle_stage_error(stage: str, exc: Exception, state: PipelineState, result: PipelineResult):
    err_summary = f"{type(exc).__name__}: {str(exc)[:200]}"
    state.fail(stage, err_summary)
    result.status = "failed"
    result.errors.append(f"{stage}: {err_summary}")
    logger.error(f"{stage}_failed", project=result.project_id, error=err_summary,
                 traceback=tb.format_exc()[-600:])


# ── resume loaders ─────────────────────────────────────────────────────────────

def _load_research(project_id: str, topic: str):
    from app.research.schemas import ResearchResult
    from app.database.models import Research as ResearchModel
    with get_session() as session:
        row = session.query(ResearchModel).filter_by(project_id=project_id).first()
        if row:
            return ResearchResult.model_validate({
                "topic": row.raw_text or topic,
                "summary": "",
                "facts": row.facts or [],
                "claims": row.claims or [],
                "statistics": row.statistics or [],
                "dates": row.dates or [],
                "people": row.people or [],
                "locations": row.locations or [],
                "uncertain_claims": row.uncertain_claims or [],
            })
    return ResearchResult(topic=topic, summary="")


def _load_script(project_id: str):
    from app.database.models import Script as ScriptModel
    from app.script.schemas import ScriptResult
    with get_session() as session:
        row = (session.query(ScriptModel)
               .filter_by(project_id=project_id)
               .order_by(ScriptModel.version.desc()).first())
        if row and row.raw_json:
            try:
                return ScriptResult.model_validate(row.raw_json)
            except Exception:
                pass
    return None


def _load_seo(project_id: str):
    from app.database.models import Metadata as MetadataModel
    from app.seo.schemas import SEOMetadata
    with get_session() as session:
        row = session.query(MetadataModel).filter_by(project_id=project_id).first()
        if row and row.title:
            try:
                return SEOMetadata.model_validate({
                    "best_title": row.title,
                    "description": row.description or "",
                    "tags": row.tags or [],
                    "hashtags": row.hashtags or [],
                    "chapters": row.chapters or [],
                })
            except Exception:
                pass
    return None
