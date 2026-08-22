"""
CLI entry point.

Usage:
    python -m app.main create --topic "Black holes"
    python -m app.main create --topic "Black holes" --upload
    python -m app.main run --topic "How black holes work"     # full agent pipeline
    python -m app.main status --project abc12345
    python -m app.main publish --project abc12345
    python -m app.main scheduler start
    python -m app.main scheduler trigger
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from app.config.logging_config import configure_logging
from app.config.settings import settings


def _safe_echo(text: str) -> None:
    try:
        click.echo(text)
    except UnicodeEncodeError:
        safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        click.echo(safe)


@click.group()
def cli():
    """AI YouTube Automation -- automated video generation pipeline."""
    configure_logging()


# ── create ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--topic", "-t", required=True, help="Video topic")
@click.option("--language", "-l", default="English", show_default=True)
@click.option("--duration", "-d", default=480, show_default=True, type=int,
              help="Target duration in seconds")
@click.option("--style", "-s", default="documentary", show_default=True)
@click.option("--aspect-ratio", default="16:9", show_default=True)
@click.option("--provider", default=None, help="LLM provider override (ollama|openai|gemini)")
@click.option("--project-id", default=None, help="Resume existing project")
@click.option("--upload", is_flag=True, default=False,
              help="Upload to YouTube after generating metadata+thumbnail")
@click.option("--video-path", default=None, type=click.Path(),
              help="Path to rendered MP4 (required for --upload)")
@click.option("--output-json", is_flag=True, help="Print result as JSON")
def create(topic, language, duration, style, aspect_ratio, provider,
           project_id, upload, video_path, output_json):
    """
    Run the pipeline: research -> script -> SEO -> thumbnail [-> YouTube upload].

    Example:
        python -m app.main create --topic "How black holes work"
        python -m app.main create --topic "How black holes work" --upload --video-path final.mp4
    """
    from app.pipeline.orchestrator import Orchestrator

    _safe_echo(f"\n[VIDEO] AI YouTube Automation  |  {settings.app_version}")
    _safe_echo(f"[TOPIC] Topic  : {topic}")
    _safe_echo(f"[LLM]   LLM    : {provider or settings.llm_provider}")
    _safe_echo(f"[UPLOAD]Upload : {'YES' if upload else 'no (--upload to enable)'}")
    _safe_echo("-" * 55)

    orchestrator = Orchestrator(llm_override=provider)
    result = orchestrator.run(
        topic=topic,
        language=language,
        target_duration_seconds=duration,
        style=style,
        aspect_ratio=aspect_ratio,
        project_id=project_id,
        upload_to_youtube=upload,
        video_path=Path(video_path) if video_path else None,
    )

    if output_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    _print_result(result)


# ── status ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", "-p", required=True, help="Project ID")
def status(project):
    """Show pipeline status for a project."""
    from app.database.session import init_db
    from app.pipeline.state import PipelineState

    init_db()
    state = PipelineState(project)
    summary = state.get_summary()

    _safe_echo(f"\n[STATUS] Project: {project}")
    _safe_echo("-" * 40)
    for stage, stage_status in summary.items():
        icon = {
            "complete": "[OK]  ", "running": "[...] ",
            "failed": "[ERR] ", "pending": "[   ] ", "skipped": "[SKIP]",
        }.get(stage_status, "[?]   ")
        _safe_echo(f"  {icon}  {stage:<15} {stage_status}")


# ── publish ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", "-p", required=True, help="Project ID")
def publish(project):
    """
    Publish an already-uploaded private/unlisted YouTube video.

    This is the human-review gate — call this command once you have
    watched the private video and confirmed it is ready to go public.
    Requires AUTO_PUBLISH=true OR explicit call to this command.
    """
    from app.database.models import YouTubeUpload
    from app.database.session import get_session, init_db
    from app.youtube.uploader import YouTubeUploader

    init_db()
    with get_session() as s:
        row = s.query(YouTubeUpload).filter_by(project_id=project).first()
        video_id = row.video_id if row else None

    if not video_id:
        click.echo(f"[ERR] No YouTube upload found for project {project!r}. "
                   "Run 'create --upload' first.")
        return

    click.echo(f"Publishing video {video_id} to public ...")
    try:
        YouTubeUploader(project_id=project).publish(video_id)
        click.echo(f"[OK] Published: https://www.youtube.com/watch?v={video_id}")
    except Exception as exc:
        click.echo(f"[ERR] Publish failed: {exc}")


# ── run (full agent pipeline) ──────────────────────────────────────────────────

@cli.command("run")
@click.option("--topic", "-t", required=True, help="Video topic")
@click.option("--niche", "-n", default=None, help="Niche preset name (science|space|history|tech|psychology)")
@click.option("--language", "-l", default="English", show_default=True)
@click.option("--duration", "-d", default=480, show_default=True, type=int,
              help="Target duration in seconds")
@click.option("--style", "-s", default="documentary", show_default=True)
@click.option("--provider", default=None, help="LLM provider override (openai|gemini)")
@click.option("--upload", is_flag=True, default=False,
              help="Upload to YouTube after rendering (requires YouTube credentials)")
def run_pipeline(topic, niche, language, duration, style, provider, upload):
    """
    Run the FULL agent pipeline: trend → research → script → storyboard →
    images → voice → music → video → SEO → thumbnail → quality → [upload].

    Example:
        python -m app.main run --topic "How black holes work"
        python -m app.main run --niche space --topic "James Webb discoveries" --upload
    """
    import uuid
    from pathlib import Path as _Path
    from app.database.session import init_db
    from app.agents.base import AgentContext
    from app.llm.factory import get_llm_provider

    _safe_echo(f"\n[VIDEO] Full agent pipeline  |  {settings.app_version}")
    _safe_echo(f"[TOPIC] {topic}")
    _safe_echo(f"[LLM]   {provider or settings.llm_provider}")
    _safe_echo("-" * 55)

    init_db()

    # Apply niche config if given
    if niche:
        from app.scheduler.niche_config import get_niche_config
        nc = get_niche_config(niche)
        language = language or nc.language
        duration = duration or nc.target_duration_seconds
        style = style or nc.style

    project_id = str(uuid.uuid4())[:8]
    output_dir = settings.output_dir / project_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Insert Project row so FK constraints in api_costs / research / etc. are satisfied
    from app.database.models import Project
    from app.database.session import get_session
    with get_session() as s:
        s.add(Project(
            id=project_id, topic=topic, language=language,
            target_duration_seconds=duration, style=style,
            aspect_ratio="16:9", status="created",
        ))

    llm = get_llm_provider(provider)
    context = AgentContext(
        project_id=project_id,
        topic=topic,
        language=language,
        style=style,
        target_duration_seconds=duration,
        output_dir=output_dir,
    )

    _safe_echo(f"[ID]    Project ID: {project_id}")
    _safe_echo(f"[DIR]   Output: {output_dir}")
    _safe_echo("")

    # ── Agent pipeline ──────────────────────────────────────────────────────
    agents_run = []

    def _step(name, agent_fn):
        _safe_echo(f"  [RUN] {name}...")
        result = agent_fn()
        icon = "[OK] " if result.success else "[ERR]"
        _safe_echo(f"  {icon} {name} ({result.duration_seconds:.1f}s)")
        agents_run.append({"name": name, "ok": result.success, "error": result.error})
        return result

    from app.agents.research_agent import ResearchAgent
    from app.agents.script_agent import ScriptAgent
    from app.agents.character_agent import CharacterAgent
    from app.agents.storyboard_agent import StoryboardAgent
    from app.agents.asset_agent import AssetAgent
    from app.agents.audio_director_agent import AudioDirectorAgent
    from app.agents.voice_agent import VoiceAgent
    from app.agents.music_agent import MusicAgent
    from app.agents.video_edit_agent import VideoEditAgent
    from app.agents.seo_agent import SEOAgent
    from app.agents.thumbnail_agent import ThumbnailAgent
    from app.agents.quality_agent import QualityAgent

    _step("Research", lambda: ResearchAgent(llm=llm).run(context))
    if context.research is None:
        _safe_echo("[ERR] Research failed — aborting pipeline.")
        return

    _step("Script", lambda: ScriptAgent(llm=llm).run(context))
    if context.script is None:
        _safe_echo("[ERR] Script generation failed — aborting pipeline.")
        return

    _step("Characters", lambda: CharacterAgent(llm=llm).run(context))
    _step("Storyboard", lambda: StoryboardAgent(llm=llm).run(context))
    _step("Images", lambda: AssetAgent().run(context))
    _step("Audio direction", lambda: AudioDirectorAgent().run(context))
    _step("Voice", lambda: VoiceAgent().run(context))
    _step("Music", lambda: MusicAgent().run(context))
    _step("Video edit", lambda: VideoEditAgent().run(context))
    _step("SEO metadata", lambda: SEOAgent(llm=llm).run(context))
    _step("Thumbnail", lambda: ThumbnailAgent(llm=llm).run(context))
    quality = _step("Quality check", lambda: QualityAgent().run(context))
    quality_passed = bool(quality.success and quality.output and quality.output.passed)

    if upload and quality_passed and context.video_path and context.video_path.exists():
        from app.agents.youtube_agent import YouTubeAgent
        _step("YouTube upload", lambda: YouTubeAgent().run(context))
    elif upload and not quality_passed:
        _safe_echo("[ERR] Upload blocked because the quality gate failed.")

    # ── Summary ─────────────────────────────────────────────────────────────
    _safe_echo(f"\n{'='*55}")
    _safe_echo(f"  Project: {project_id}")
    if context.video_path:
        _safe_echo(f"  Video  : {context.video_path}")
    if context.thumbnail_path:
        _safe_echo(f"  Thumb  : {context.thumbnail_path}")
    if context.seo:
        _safe_echo(f"  Title  : {context.seo.best_title}")
    if context.youtube_url:
        _safe_echo(f"  [YT]   : {context.youtube_url}")
        _safe_echo("  Status : PRIVATE — run 'publish --project' when ready")
    if context.errors:
        _safe_echo(f"\n  Warnings ({len(context.errors)}):")
        for e in context.errors:
            _safe_echo(f"    - {e}")
    _safe_echo("")


# ── scheduler ─────────────────────────────────────────────────────────────────

@cli.group()
def scheduler():
    """Manage the autonomous video generation scheduler."""
    pass


@scheduler.command("start")
@click.option("--niche", "-n", default=None, help="Content niche (or preset name)")
@click.option("--interval-days", "-i", default=None, type=int,
              help="Run every N days (default from settings)")
@click.option("--now", is_flag=True, default=False,
              help="Run one job immediately, then schedule future runs")
@click.option("--provider", default=None, help="LLM provider override")
def scheduler_start(niche, interval_days, now, provider):
    """
    Start the autonomous scheduler.

    Runs the full pipeline every N days for the configured niche,
    automatically picks trending topics, and uploads as PRIVATE.

    Example:
        python -m app.main scheduler start --niche science --interval-days 3
        python -m app.main scheduler start --now   # run one job now then schedule
    """
    import time

    from app.scheduler.job_scheduler import VideoScheduler

    niche_val = niche or settings.scheduler_niche
    days = interval_days or settings.scheduler_interval_days

    _safe_echo(f"\n[SCHED] Autonomous scheduler starting")
    _safe_echo(f"  Niche    : {niche_val}")
    _safe_echo(f"  Interval : every {days} day(s)")
    _safe_echo(f"  LLM      : {provider or settings.llm_provider}")
    _safe_echo("-" * 55)

    sched = VideoScheduler(
        niche=niche_val,
        interval_days=days,
        llm_provider_override=provider,
    )
    sched.start(run_immediately=now)

    next_run = sched.next_run_time()
    if next_run:
        _safe_echo(f"  Next run : {next_run.strftime('%Y-%m-%d %H:%M UTC')}")

    _safe_echo("\n[SCHED] Running... Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        sched.stop()
        _safe_echo("\n[SCHED] Scheduler stopped.")


@scheduler.command("trigger")
@click.option("--niche", "-n", default=None, help="Content niche (or preset name)")
@click.option("--provider", default=None, help="LLM provider override")
def scheduler_trigger(niche, provider):
    """
    Trigger one immediate scheduled job without starting the recurring scheduler.

    Useful for testing the full pipeline end-to-end without waiting for the interval.

    Example:
        python -m app.main scheduler trigger --niche science
    """
    from app.scheduler.job_scheduler import VideoScheduler

    niche_val = niche or settings.scheduler_niche
    _safe_echo(f"\n[SCHED] Running one-off job for niche: {niche_val}")
    sched = VideoScheduler(niche=niche_val, llm_provider_override=provider)
    project_id = sched.trigger_now()
    _safe_echo(f"\n[OK]   Job complete. Project ID: {project_id}")
    _safe_echo(f"       Run 'status --project {project_id}' to see details.")


# ── api ────────────────────────────────────────────────────────────────────────

@cli.command("api")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, type=int, show_default=True)
@click.option("--reload", is_flag=True, default=False, help="Enable hot-reload (dev only)")
def serve_api(host, port, reload):
    """
    Start the FastAPI REST API server.

    Example:
        python -m app.main api
        python -m app.main api --port 8080 --reload
    """
    try:
        import uvicorn
    except ImportError:
        click.echo("[ERR] uvicorn not installed. Run: pip install uvicorn[standard]")
        return

    _safe_echo(f"\n[API] Starting FastAPI server on http://{host}:{port}")
    _safe_echo(f"[API] Docs: http://{host}:{port}/docs")
    _safe_echo(f"[API] Health: http://{host}:{port}/health\n")
    uvicorn.run(
        "app.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


# ── cost ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", "-p", required=True, help="Project ID")
def cost(project):
    """Show estimated API cost for a project."""
    from app.database.models import ApiCost
    from app.database.session import get_session, init_db

    init_db()
    with get_session() as s:
        rows = s.query(ApiCost).filter_by(project_id=project).all()
        table = [(r.operation, r.provider, r.model or "",
                  r.input_tokens, r.output_tokens, r.estimated_cost_usd)
                 for r in rows]

    if not table:
        click.echo(f"No cost records found for project {project!r}")
        return

    _safe_echo(f"\n[COST] Cost breakdown for project: {project}")
    _safe_echo("-" * 70)
    total = 0.0
    for op, prov, model, inp, out, usd in table:
        click.echo(f"  {op:<20} {prov:<10} {model:<25} in={inp:>6} out={out:>6}  ${usd:.6f}")
        total += usd
    _safe_echo("-" * 70)
    click.echo(f"  {'TOTAL':<20}  ${total:.6f}")
    if total == 0.0:
        click.echo("  (Local providers have no API cost)")


# ── helpers ────────────────────────────────────────────────────────────────────

def _print_result(result) -> None:
    ok = result.status not in ("failed",)
    _safe_echo(f"\n{'[OK]' if ok else '[ERR]'}  Status       : {result.status}")
    click.echo(f"  ID           : {result.project_id}")
    click.echo(f"  Output dir   : {result.output_dir}")

    if result.script_title:
        click.echo(f"  Script title : {result.script_title}")
    if result.script_sections:
        click.echo(f"  Sections     : {result.script_sections}")
    if result.estimated_duration_seconds:
        m, s = divmod(result.estimated_duration_seconds, 60)
        click.echo(f"  Duration     : {m}m {s}s")

    if result.seo_title:
        _safe_echo(f"\n  [SEO] YouTube Title:")
        _safe_echo(f"    {result.seo_title}")
    if result.seo_tags:
        _safe_echo(f"  [SEO] Tags ({len(result.seo_tags)}):")
        _safe_echo(f"    {', '.join(result.seo_tags[:10])}{'...' if len(result.seo_tags) > 10 else ''}")
    if result.seo_hashtags:
        _safe_echo(f"  [SEO] Hashtags: {' '.join(result.seo_hashtags[:5])}")
    if result.seo_chapters:
        _safe_echo(f"  [SEO] Chapters ({len(result.seo_chapters)}):")
        for ch in result.seo_chapters[:5]:
            _safe_echo(f"    {ch.get('time','?')} - {ch.get('label','')}")
        if len(result.seo_chapters) > 5:
            _safe_echo(f"    ... (+{len(result.seo_chapters)-5} more)")

    if result.thumbnail_path:
        click.echo(f"\n  Thumbnail    : {result.thumbnail_path}")

    if result.youtube_url:
        _safe_echo(f"\n  [YT] YouTube URL    : {result.youtube_url}")
        _safe_echo(f"  [YT] Video ID       : {result.youtube_video_id}")
        _safe_echo(f"  [YT] Privacy status : {result.youtube_privacy_status}")
        if result.youtube_privacy_status == "private":
            _safe_echo("  [YT] Run 'publish --project <id>' when ready to go public.")

    if result.estimated_cost_usd > 0:
        click.echo(f"\n  Est. cost    : ${result.estimated_cost_usd:.6f} USD")
    else:
        click.echo("\n  Est. cost    : $0.00 (local provider)")

    if result.errors:
        click.echo("\n  Errors:")
        for err in result.errors:
            click.echo(f"   * {err}")
    click.echo("")


if __name__ == "__main__":
    cli()
