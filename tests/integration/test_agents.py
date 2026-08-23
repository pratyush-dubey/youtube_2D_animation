"""
Integration tests for the multi-agent pipeline.

All tests use mocked LLMs and mocked file operations — no real network calls,
no FFmpeg, no TTS API required. The tests verify the agent contracts:
  - Each agent reads from AgentContext and writes back to it
  - Failures are captured in AgentResult (not raised)
  - The pipeline is resumable (agents skip if output already present)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base


# ── Shared DB + path fixtures ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.sqlite3"
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import app.database.session as db_mod
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSession)

    monkeypatch.setattr("app.config.settings.settings.output_dir", tmp_path / "output")
    monkeypatch.setattr("app.config.settings.settings.project_dir", tmp_path / "projects")
    (tmp_path / "output").mkdir()
    (tmp_path / "projects").mkdir()
    yield


def _make_context(tmp_path, topic="How black holes work"):
    from app.agents.base import AgentContext
    from app.database.session import init_db
    init_db()
    project_id = "test0001"
    output_dir = tmp_path / "output" / project_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return AgentContext(
        project_id=project_id,
        topic=topic,
        language="English",
        style="documentary",
        target_duration_seconds=240,
        output_dir=output_dir,
    )


# ── Mock LLM helpers ──────────────────────────────────────────────────────────

def _make_llm(responses: list[dict]):
    """Create a mock LLM that returns pre-set JSON responses in order."""
    from app.llm.base import LLMResponse
    mock = MagicMock()
    mock.provider_name = "mock"
    mock.model = "mock-model"
    response_iter = iter(responses)

    def generate_json(prompt, schema_hint="", **kwargs):
        data = next(response_iter)
        resp = LLMResponse(
            content=json.dumps(data),
            input_tokens=100,
            output_tokens=50,
            model="mock-model",
            provider="mock",
        )
        return data, resp

    mock.generate_json.side_effect = generate_json
    return mock


# ── Sample payloads ───────────────────────────────────────────────────────────

RESEARCH_DATA = {
    "topic": "How black holes work",
    "summary": "Black holes have event horizons.",
    "facts": [{"fact": "Black holes have event horizons", "confidence": 0.99}],
    "claims": [],
    "statistics": [],
    "dates": [],
    "people": [],
    "locations": [],
    "uncertain_claims": [],
    "key_questions": [],
    "suggested_sections": ["What is a black hole?"],
}

SCRIPT_DATA = {
    "title": "How Black Holes Work",
    "hook": "Imagine the darkest place in the universe.",
    "sections": [
        {
            "id": 1, "title": "Intro",
            "narration": "Black holes are incredible.",
            "duration_seconds": 30,
            "key_facts": [],
        },
        {
            "id": 2, "title": "Formation",
            "narration": "They form from dying stars.",
            "duration_seconds": 40,
            "key_facts": [],
        },
    ],
    "conclusion": "Black holes remain mysterious.",
    "call_to_action": "Subscribe for more.",
    "estimated_duration_seconds": 240,
    "word_count": 350,
    "tone": "documentary",
}

STORYBOARD_DATA = {
    "total_scenes": 2,
    "scenes": [
        {
            "scene_id": 1,
            "duration_seconds": 8.0,
            "narration": "Black holes are incredible.",
            "visual_description": "Dark starfield",
            "image_prompt": "2D illustration of a black hole",
            "animation_type": "zoom-in",
            "camera_motion": "slow-zoom-in",
            "text_overlay": None,
            "transition": "cut",
            "music_mood": "mysterious",
            "sfx": [],
        },
        {
            "scene_id": 2,
            "duration_seconds": 10.0,
            "narration": "They form from dying stars.",
            "visual_description": "Star going supernova",
            "image_prompt": "2D illustration supernova",
            "animation_type": "pan-left",
            "camera_motion": "pan-left",
            "text_overlay": None,
            "transition": "fade",
            "music_mood": "dramatic",
            "sfx": [],
        },
    ],
}

SEO_DATA = {
    "title_candidates": [
        {
            "title": "How Black Holes Work",
            "curiosity_score": 8,
            "clarity_score": 9,
            "keyword_score": 9,
            "ctr_score": 8,
            "total_score": 34,
            "reason": "Strong keywords.",
        }
    ],
    "best_title": "How Black Holes Work",
    "description": "A complete guide to black holes. " * 10,
    "tags": ["black holes", "space", "science", "astronomy", "physics"],
    "hashtags": ["#space", "#science"],
    "chapters": [{"time": "0:00", "label": "Intro"}],
}


# ═══════════════════════════════════════════════════════════════════════════════
# ResearchAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestResearchAgent:
    def test_successful_research(self, tmp_path):
        from app.agents.research_agent import ResearchAgent
        context = _make_context(tmp_path)
        llm = _make_llm([RESEARCH_DATA])

        with patch.object(ResearchAgent, "_gather_web_facts", return_value=[]):
            agent = ResearchAgent(llm=llm)
            result = agent.run(context)

        assert result.success is True
        assert result.agent_name == "research_agent"
        assert context.research is not None
        assert len(context.research.facts) == 1
        assert (context.output_dir / "research.json").is_file()

    def test_failure_captured_in_result(self, tmp_path):
        from app.agents.research_agent import ResearchAgent
        context = _make_context(tmp_path)
        llm = MagicMock()
        llm.provider_name = "mock"
        llm.model = "mock"
        llm.generate_json.side_effect = RuntimeError("LLM offline")

        with patch.object(ResearchAgent, "_gather_web_facts", return_value=[]):
            agent = ResearchAgent(llm=llm)
            result = agent.run(context)

        assert result.success is False
        assert "LLM offline" in result.error
        assert context.research is None

    def test_web_facts_prepended_to_prompt(self, tmp_path):
        """extra_context is passed to Researcher and reaches the LLM prompt."""
        from app.agents.research_agent import ResearchAgent
        from app.research.researcher import Researcher
        context = _make_context(tmp_path)
        llm = _make_llm([RESEARCH_DATA])

        fake_facts = [{"source": "wikipedia", "content": "Black holes warp spacetime."}]
        with patch.object(ResearchAgent, "_gather_web_facts", return_value=fake_facts):
            agent = ResearchAgent(llm=llm)
            result = agent.run(context)

        # The LLM was called once — web facts should have been injected into the prompt
        assert result.success is True
        call_args = llm.generate_json.call_args
        assert call_args is not None
        prompt_used = call_args[0][0]
        assert "Black holes warp spacetime" in prompt_used

    def test_wikipedia_fallback_is_graceful(self, tmp_path):
        from app.agents.research_agent import ResearchAgent
        context = _make_context(tmp_path)
        llm = _make_llm([RESEARCH_DATA])

        agent = ResearchAgent(llm=llm)
        # Let Wikipedia fail — should still produce a result via LLM
        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            result = agent.run(context)

        assert result.success is True
        assert context.research is not None


# ═══════════════════════════════════════════════════════════════════════════════
# ScriptAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestScriptAgent:
    def test_requires_research(self, tmp_path):
        from app.agents.script_agent import ScriptAgent
        context = _make_context(tmp_path)
        # context.research is None by default
        result = ScriptAgent(llm=_make_llm([])).run(context)
        assert result.success is False
        assert "ResearchAgent" in result.error

    def test_generates_script(self, tmp_path):
        from app.agents.script_agent import ScriptAgent
        from app.research.schemas import ResearchResult
        context = _make_context(tmp_path)
        context.research = ResearchResult.model_validate(RESEARCH_DATA)

        llm = _make_llm([SCRIPT_DATA])
        result = ScriptAgent(llm=llm).run(context)

        assert result.success is True
        assert context.script is not None
        assert context.script.title == "How Black Holes Work"
        assert len(context.script.sections) == 2

    def test_script_written_to_disk(self, tmp_path):
        from app.agents.script_agent import ScriptAgent
        from app.research.schemas import ResearchResult
        context = _make_context(tmp_path)
        context.research = ResearchResult.model_validate(RESEARCH_DATA)

        ScriptAgent(llm=_make_llm([SCRIPT_DATA])).run(context)

        assert (context.output_dir / "script.json").exists()
        data = json.loads((context.output_dir / "script.json").read_text())
        assert data["title"] == "How Black Holes Work"


# ═══════════════════════════════════════════════════════════════════════════════
# StoryboardAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestStoryboardAgent:
    def _make_context_with_script(self, tmp_path):
        from app.research.schemas import ResearchResult
        from app.script.schemas import ScriptResult
        ctx = _make_context(tmp_path)
        ctx.research = ResearchResult.model_validate(RESEARCH_DATA)
        ctx.script = ScriptResult.model_validate(SCRIPT_DATA)
        return ctx

    def test_requires_script(self, tmp_path):
        from app.agents.storyboard_agent import StoryboardAgent
        ctx = _make_context(tmp_path)
        result = StoryboardAgent(llm=_make_llm([])).run(ctx)
        assert result.success is False

    def test_generates_storyboard(self, tmp_path):
        from app.agents.storyboard_agent import StoryboardAgent
        ctx = self._make_context_with_script(tmp_path)

        result = StoryboardAgent(llm=_make_llm([STORYBOARD_DATA])).run(ctx)

        assert result.success is True
        assert ctx.storyboard is not None
        assert len(ctx.storyboard) == 2

    def test_storyboard_cached_on_disk(self, tmp_path):
        from app.agents.storyboard_agent import StoryboardAgent
        ctx = self._make_context_with_script(tmp_path)

        # Write cache first
        cache = ctx.output_dir / "storyboard.json"
        cache.write_text(json.dumps(STORYBOARD_DATA), encoding="utf-8")

        llm = _make_llm([])  # no responses — should not be called
        result = StoryboardAgent(llm=llm).run(ctx)

        assert result.success is True
        assert len(ctx.storyboard) == 2

    def test_scene_normalisation(self, tmp_path):
        from app.agents.storyboard_agent import StoryboardAgent
        ctx = self._make_context_with_script(tmp_path)

        # Minimal scene — storyboard agent should fill defaults
        minimal_storyboard = {"scenes": [{"scene_id": 1}]}
        result = StoryboardAgent(llm=_make_llm([minimal_storyboard])).run(ctx)

        assert result.success is True
        scene = ctx.storyboard[0]
        assert scene["animation_type"] == "zoom-in"   # default
        assert scene["transition"] == "cut"            # default
        assert scene["music_mood"] == "calm"           # default


# ═══════════════════════════════════════════════════════════════════════════════
# AssetAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssetAgent:
    def test_requires_storyboard(self, tmp_path):
        from app.agents.asset_agent import AssetAgent
        ctx = _make_context(tmp_path)
        result = AssetAgent().run(ctx)
        assert result.success is False

    def test_mock_provider_creates_images(self, tmp_path):
        from app.agents.asset_agent import AssetAgent
        from PIL import Image
        ctx = _make_context(tmp_path)
        ctx.storyboard = STORYBOARD_DATA["scenes"]

        # Force placeholder — no cloud API calls
        def generate(_self, _prompt, output, *_args, **_kwargs):
            gradient = Image.linear_gradient("L").resize((768, 432))
            Image.merge("RGB", (gradient, gradient.transpose(Image.Transpose.FLIP_TOP_BOTTOM), gradient)).save(output, "JPEG")
            return output

        with patch.object(AssetAgent, "_generate_image", generate):
            result = AssetAgent().run(ctx)

        assert result.success is True
        assert len(ctx.images) == 2
        for scene_id, path in ctx.images.items():
            assert path.exists()

    def test_resumes_existing_images(self, tmp_path):
        from app.agents.asset_agent import AssetAgent
        from PIL import Image
        ctx = _make_context(tmp_path)
        ctx.storyboard = STORYBOARD_DATA["scenes"]

        def generate(_self, _prompt, output, *_args, **_kwargs):
            gradient = Image.linear_gradient("L").resize((768, 432))
            Image.merge("RGB", (gradient, gradient.transpose(Image.Transpose.FLIP_TOP_BOTTOM), gradient)).save(output, "JPEG")
            return output

        with patch.object(AssetAgent, "_generate_image", generate):
            first = AssetAgent().run(ctx)
        assert first.success is True

        with patch.object(AssetAgent, "_generate_image", side_effect=Exception("should not be called")):
            result = AssetAgent().run(ctx)

        assert result.success is True
        assert len(ctx.images) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# VoiceAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoiceAgent:
    def test_requires_storyboard(self, tmp_path):
        from app.agents.voice_agent import VoiceAgent
        ctx = _make_context(tmp_path)
        result = VoiceAgent().run(ctx)
        assert result.success is False

    def test_synthesizes_audio(self, tmp_path, monkeypatch):
        """gTTS synthesises audio — skipped when gtts package not installed."""
        pytest.importorskip("gtts", reason="gtts not installed")
        from app.agents.voice_agent import VoiceAgent
        ctx = _make_context(tmp_path)
        ctx.storyboard = STORYBOARD_DATA["scenes"]
        monkeypatch.setattr("app.config.settings.settings.tts_provider", "gtts")

        # Mock gTTS.save to write a dummy file without network access
        def fake_gtts_init(self_gtts, text, lang, slow):
            pass

        def fake_gtts_save(self_gtts, path):
            Path(path).write_bytes(b"fake_audio_" + b"\x00" * 600)

        with patch("gtts.gTTS.__init__", fake_gtts_init), \
             patch("gtts.gTTS.save", fake_gtts_save):
            result = VoiceAgent().run(ctx)

        assert result.success is True
        assert len(ctx.narration_files) == 2

    def test_empty_narration_skipped(self, tmp_path, monkeypatch):
        """Empty scene narration is skipped without error."""
        pytest.importorskip("gtts", reason="gtts not installed")
        from app.agents.voice_agent import VoiceAgent
        ctx = _make_context(tmp_path)
        ctx.storyboard = [
            {**STORYBOARD_DATA["scenes"][0], "narration": ""},  # empty
            STORYBOARD_DATA["scenes"][1],
        ]
        monkeypatch.setattr("app.config.settings.settings.tts_provider", "gtts")

        def fake_gtts_init(self_gtts, text, lang, slow):
            pass

        def fake_gtts_save(self_gtts, path):
            Path(path).write_bytes(b"fake_audio_" + b"\x00" * 600)

        with patch("gtts.gTTS.__init__", fake_gtts_init), \
             patch("gtts.gTTS.save", fake_gtts_save):
            result = VoiceAgent().run(ctx)

        assert result.success is True
        assert 1 not in ctx.narration_files   # scene 1 had empty narration
        assert 2 in ctx.narration_files


# ═══════════════════════════════════════════════════════════════════════════════
# MusicAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestMusicAgent:
    def test_returns_none_gracefully_when_offline(self, tmp_path):
        """When all downloads fail, the agent either uses a silent FFmpeg fallback
        or sets music_path=None.  Either way it must succeed (not crash)."""
        from app.agents.music_agent import MusicAgent
        import shutil
        ctx = _make_context(tmp_path)
        ctx.storyboard = STORYBOARD_DATA["scenes"]

        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            result = MusicAgent().run(ctx)

        # Agent must not fail even without music
        assert result.success is True
        # If FFmpeg is available a silent fallback is generated; otherwise music_path is None.
        # Both are acceptable — do not assert a specific value.
        if not shutil.which("ffmpeg"):
            assert ctx.music_path is None

    def test_local_track_used_when_available(self, tmp_path, monkeypatch):
        from app.agents.music_agent import MusicAgent, _MUSIC_DIR
        ctx = _make_context(tmp_path)
        ctx.storyboard = STORYBOARD_DATA["scenes"]

        # Create a fake local music library
        music_dir = tmp_path / "assets" / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        track_file = music_dir / "test_track.mp3"
        track_file.write_bytes(b"\xff\xfb" + b"\x00" * 12_000)  # passes minimum asset-size gate
        meta_file = music_dir / "metadata.json"
        meta_file.write_text(json.dumps([{
            "file": "test_track.mp3",
            "license": "CC0",
            "author": "Test",
            "commercial_use": True,
            "mood": ["mysterious", "documentary"],
        }]))

        monkeypatch.setattr("app.agents.music_agent._MUSIC_DIR", music_dir)
        monkeypatch.setattr("app.agents.music_agent._META_FILE", meta_file)

        result = MusicAgent().run(ctx)

        assert result.success is True
        assert ctx.music_path is not None
        assert ctx.music_path.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# SEOAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestSEOAgent:
    def _make_full_context(self, tmp_path):
        from app.research.schemas import ResearchResult
        from app.script.schemas import ScriptResult
        ctx = _make_context(tmp_path)
        ctx.research = ResearchResult.model_validate(RESEARCH_DATA)
        ctx.script = ScriptResult.model_validate(SCRIPT_DATA)
        return ctx

    def test_requires_script_and_research(self, tmp_path):
        from app.agents.seo_agent import SEOAgent
        ctx = _make_context(tmp_path)
        result = SEOAgent(llm=_make_llm([])).run(ctx)
        assert result.success is False

    def test_generates_seo_metadata(self, tmp_path):
        from app.agents.seo_agent import SEOAgent
        ctx = self._make_full_context(tmp_path)

        result = SEOAgent(llm=_make_llm([SEO_DATA])).run(ctx)

        assert result.success is True
        assert ctx.seo is not None
        assert ctx.seo.best_title == "How Black Holes Work"
        assert len(ctx.seo.tags) >= 5

    def test_seo_written_to_disk(self, tmp_path):
        from app.agents.seo_agent import SEOAgent
        ctx = self._make_full_context(tmp_path)
        SEOAgent(llm=_make_llm([SEO_DATA])).run(ctx)
        assert (ctx.output_dir / "seo.json").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# ThumbnailAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestThumbnailAgent:
    def test_requires_seo(self, tmp_path):
        from app.agents.thumbnail_agent import ThumbnailAgent
        ctx = _make_context(tmp_path)
        result = ThumbnailAgent(llm=MagicMock()).run(ctx)
        assert result.success is False

    def test_generates_thumbnail(self, tmp_path):
        from app.agents.thumbnail_agent import ThumbnailAgent
        from app.seo.schemas import SEOMetadata
        ctx = _make_context(tmp_path)
        ctx.seo = SEOMetadata.model_validate(SEO_DATA)

        # ThumbnailGenerator uses Pillow — this should work without mocking
        result = ThumbnailAgent(llm=MagicMock()).run(ctx)

        assert result.success is True
        assert ctx.thumbnail_path is not None
        assert ctx.thumbnail_path.exists()
        assert ctx.thumbnail_path.stat().st_size > 100


# ═══════════════════════════════════════════════════════════════════════════════
# QualityAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestQualityAgent:
    def test_passes_when_seo_present(self, tmp_path):
        from app.agents.quality_agent import QualityAgent
        from app.seo.schemas import SEOMetadata
        ctx = _make_context(tmp_path)
        ctx.seo = SEOMetadata.model_validate(SEO_DATA)

        result = QualityAgent().run(ctx)

        assert result.success is True
        report = result.output
        seo_checks = [c for c in report.checks if c["check"].startswith("seo")]
        assert all(c["passed"] for c in seo_checks)

    def test_fails_when_no_video(self, tmp_path):
        from app.agents.quality_agent import QualityAgent
        from app.seo.schemas import SEOMetadata
        ctx = _make_context(tmp_path)
        ctx.seo = SEOMetadata.model_validate(SEO_DATA)

        result = QualityAgent().run(ctx)
        report = result.output

        # video_exists check should fail (no video generated yet)
        video_check = next(c for c in report.checks if c["check"] == "video_exists")
        assert video_check["passed"] is False

    def test_report_dict_serialisable(self, tmp_path):
        from app.agents.quality_agent import QualityAgent
        ctx = _make_context(tmp_path)

        result = QualityAgent().run(ctx)
        d = result.output.to_dict()
        assert "passed" in d
        assert "checks" in d
        # Should be JSON-serialisable
        json.dumps(d)


# ═══════════════════════════════════════════════════════════════════════════════
# TrendAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrendAgent:
    def test_llm_fallback_used_when_no_external_api(self, tmp_path):
        from app.agents.trend_agent import TrendAgent

        ctx = _make_context(tmp_path, topic="")
        llm_response = [
            {"topic": "How black holes form", "reason": "Trending topic", "estimated_search_volume": "high"},
            {"topic": "Dark matter explained", "reason": "High interest", "estimated_search_volume": "medium"},
        ]
        llm = _make_llm([llm_response])

        with patch("urllib.request.urlopen", side_effect=Exception("offline")):
            result = TrendAgent(niche="science", llm=llm).run(ctx)

        assert result.success is True
        assert len(ctx.trending_topics) > 0
        assert ctx.trending_topics[0]["source"] == "llm"

    def test_topics_sorted_by_score(self, tmp_path):
        from app.agents.trend_agent import TrendAgent
        ctx = _make_context(tmp_path, topic="")

        # LLM returns list directly (as the agent handles both list and dict)
        llm_response = [
            {"topic": "Topic A", "reason": "High score", "estimated_search_volume": "high"},
        ]
        llm = _make_llm([llm_response])
        with patch("urllib.request.urlopen", side_effect=Exception("offline")):
            TrendAgent(niche="space", llm=llm).run(ctx)

        scores = [t.get("score", 0) for t in ctx.trending_topics]
        assert scores == sorted(scores, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# AgentContext — data flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentContext:
    def test_errors_accumulate_across_agents(self, tmp_path):
        from app.agents.base import Agent, AgentContext
        from app.agents.research_agent import ResearchAgent

        ctx = _make_context(tmp_path)
        # Cause a failure without web mocking (research needs a DB project row first)
        llm = MagicMock()
        llm.provider_name = "mock"
        llm.model = "mock"
        llm.generate_json.side_effect = RuntimeError("crash")

        with patch.object(ResearchAgent, "_gather_web_facts", return_value=[]):
            ResearchAgent(llm=llm).run(ctx)

        # The error is captured in context.errors
        assert any("crash" in e for e in ctx.errors)

    def test_context_output_dir_is_path(self, tmp_path):
        ctx = _make_context(tmp_path)
        assert isinstance(ctx.output_dir, Path)

    def test_agent_result_has_duration(self, tmp_path):
        from app.agents.quality_agent import QualityAgent
        from app.seo.schemas import SEOMetadata
        ctx = _make_context(tmp_path)
        ctx.seo = SEOMetadata.model_validate(SEO_DATA)

        result = QualityAgent().run(ctx)
        assert result.duration_seconds >= 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# NicheConfig
# ═══════════════════════════════════════════════════════════════════════════════

class TestNicheConfig:
    def test_preset_science_loaded(self):
        from app.scheduler.niche_config import get_niche_config
        nc = get_niche_config("science")
        assert nc.niche == "science and technology"
        assert nc.style == "documentary"
        assert "science" in nc.base_tags

    def test_unknown_niche_uses_name_as_topic(self):
        from app.scheduler.niche_config import get_niche_config
        nc = get_niche_config("cooking recipes")
        assert nc.niche == "cooking recipes"

    def test_all_presets_have_required_fields(self):
        from app.scheduler.niche_config import PRESET_NICHES
        for name, nc in PRESET_NICHES.items():
            assert nc.niche, f"{name} missing niche"
            assert nc.style, f"{name} missing style"
            assert nc.target_duration_seconds > 0, f"{name} invalid duration"

    def test_niche_to_dict(self):
        from app.scheduler.niche_config import get_niche_config
        d = get_niche_config("space").to_dict()
        assert "niche" in d
        assert "style" in d
        assert "target_duration_seconds" in d


# ═══════════════════════════════════════════════════════════════════════════════
# VideoScheduler
# ═══════════════════════════════════════════════════════════════════════════════

class TestVideoScheduler:
    def test_scheduler_initialises(self):
        from app.scheduler.job_scheduler import VideoScheduler
        sched = VideoScheduler(niche="science", interval_days=3)
        assert sched.niche_name == "science"
        assert sched.interval_days == 3
        assert not sched.is_running()

    def test_trigger_now_runs_pipeline(self, tmp_path, monkeypatch):
        from app.scheduler.job_scheduler import VideoScheduler

        monkeypatch.setattr("app.config.settings.settings.output_dir", tmp_path / "output")
        (tmp_path / "output").mkdir(exist_ok=True)

        # Mock the full pipeline so we don't need real LLMs
        sched = VideoScheduler(niche="science", interval_days=3)
        with patch.object(sched, "_run_pipeline") as mock_pipeline:
            project_id = sched.trigger_now()

        assert project_id  # returns a project_id string
        mock_pipeline.assert_called_once()

    def test_scheduler_niche_config_applied(self):
        """VideoScheduler picks up NicheConfig for the given niche name."""
        from app.scheduler.job_scheduler import VideoScheduler
        from app.scheduler.niche_config import PRESET_NICHES
        sched = VideoScheduler(niche="space", interval_days=7)
        assert sched.niche_config.style == PRESET_NICHES["space"].style
        assert sched.interval_days == 7
