"""
Tests for SEO metadata generator, thumbnail renderer, and YouTube uploader.
All run offline — no real LLM, YouTube API, or Pillow rendering unless available.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, Project


# ── DB fixture ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.sqlite3"
    test_engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    import app.database.session as db_mod
    monkeypatch.setattr(db_mod, "engine", test_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSession)
    monkeypatch.setattr("app.config.settings.settings.output_dir", tmp_path / "output")
    (tmp_path / "output").mkdir()
    yield


def _make_project(project_id: str = "seo001"):
    from app.database.session import get_session
    from app.database.models import Project as Proj
    with get_session() as s:
        s.add(Proj(id=project_id, topic="How black holes work"))


# ── Mock LLM ─────────────────────────────────────────────────────────────────

SEO_JSON = {
    "title_candidates": [
        {
            "title": "How Black Holes Work: Complete Guide",
            "curiosity_score": 8,
            "clarity_score": 9,
            "keyword_score": 9,
            "ctr_score": 8,
            "total_score": 34,
            "reason": "Clear keyword-first title with high search intent.",
        },
        {
            "title": "Black Holes Explained: What Scientists Know",
            "curiosity_score": 7,
            "clarity_score": 9,
            "keyword_score": 8,
            "ctr_score": 7,
            "total_score": 31,
            "reason": "Authority signal with 'scientists'.",
        },
    ],
    "best_title": "How Black Holes Work: Complete Guide",
    "description": (
        "Black holes are among the most extreme objects in the universe. "
        "In this video, we break down exactly how they form, what happens at the event horizon, "
        "and why Hawking radiation means even black holes don't last forever.\n\n"
        "What you'll learn:\n"
        "► What a black hole actually is\n"
        "► How stellar black holes form from dying stars\n"
        "► The event horizon explained simply\n"
        "► Hawking radiation and black hole evaporation\n"
        "► The first ever image of a black hole (2019)\n\n"
        "CHAPTERS\n"
        "0:00 Intro\n"
        "0:45 What Is a Black Hole?\n"
        "2:15 How Black Holes Form\n"
        "3:30 The Event Horizon\n"
        "5:00 Hawking Radiation\n"
        "6:30 The First Black Hole Image\n\n"
        "SOURCES\n"
        "Based on publicly available astrophysics research and NASA documentation.\n\n"
        "DISCLAIMER: This video is for educational purposes.\n\n"
        "#BlackHoles #Astrophysics #Space"
    ),
    "tags": [
        "black holes", "how black holes work", "black hole explained",
        "event horizon", "hawking radiation", "stephen hawking",
        "astrophysics", "space science", "nasa", "astronomy",
        "black hole image", "EHT", "M87 black hole", "spacetime",
        "general relativity", "singularity", "science documentary",
        "universe explained", "physics", "cosmos",
    ],
    "hashtags": ["#BlackHoles", "#Astrophysics", "#Space"],
    "chapters": [
        {"time": "0:00", "label": "Intro"},
        {"time": "0:45", "label": "What Is a Black Hole?"},
        {"time": "2:15", "label": "How Black Holes Form"},
        {"time": "3:30", "label": "The Event Horizon"},
        {"time": "5:00", "label": "Hawking Radiation"},
        {"time": "6:30", "label": "The First Black Hole Image"},
    ],
    "category": "Science & Technology",
    "default_language": "en",
}

THUMBNAIL_JSON = {
    "concepts": [
        {
            "id": 1,
            "background_color": "#0d1117",
            "background_color_2": "#1a2332",
            "main_text": "BLACK HOLES",
            "sub_text": "How They Really Work",
            "text_color": "#ffffff",
            "accent_color": "#3b82f6",
            "focal_image_description": "dramatic black hole with glowing accretion disk",
            "layout": "text-left-image-right",
            "emotion": "awe",
            "ctr_score": 9,
            "reason": "Dark dramatic background, bold text, high contrast",
        }
    ],
    "best_concept_id": 1,
}


class MockLLM:
    provider_name = "mock"
    model = "mock-model"

    def __init__(self, responses):
        self._responses = iter(responses)

    def generate_json(self, prompt, schema_hint="", **kwargs):
        from app.llm.base import LLMResponse
        data = next(self._responses)
        resp = LLMResponse(content=json.dumps(data), input_tokens=100,
                           output_tokens=200, model="mock-model", provider="mock")
        return data, resp

    def generate(self, prompt, **kwargs):
        from app.llm.base import LLMResponse
        return LLMResponse(content="", input_tokens=0, output_tokens=0,
                           model="mock-model", provider="mock")


# ── SEO Schema tests ──────────────────────────────────────────────────────────

class TestSEOSchemas:

    def test_valid_full_schema(self):
        from app.seo.schemas import SEOMetadata
        m = SEOMetadata.model_validate(SEO_JSON)
        assert m.best_title == "How Black Holes Work: Complete Guide"
        assert len(m.title_candidates) == 2
        assert len(m.tags) == 20
        assert len(m.hashtags) == 3
        assert len(m.chapters) == 6
        assert m.chapters[0].time == "0:00"
        assert m.chapters[0].label == "Intro"

    def test_tags_coerced_from_none(self):
        from app.seo.schemas import SEOMetadata
        m = SEOMetadata.model_validate({"best_title": "T", "description": "D", "tags": None})
        assert m.tags == []

    def test_best_title_fallback(self):
        from app.seo.schemas import SEOMetadata
        m = SEOMetadata.model_validate({"best_title": "", "description": "D"})
        assert m.best_title == "Untitled Video"

    def test_best_title_truncated(self):
        from app.seo.schemas import SEOMetadata
        long_title = "A" * 200
        m = SEOMetadata.model_validate({"best_title": long_title, "description": "D"})
        assert len(m.best_title) == 100

    def test_best_tags_str(self):
        from app.seo.schemas import SEOMetadata
        m = SEOMetadata.model_validate(SEO_JSON)
        tags_str = m.best_tags_str()
        assert "black holes" in tags_str
        assert "," in tags_str

    def test_title_candidate_scores(self):
        from app.seo.schemas import TitleCandidate
        c = TitleCandidate(title="Test", curiosity_score=8, clarity_score=9,
                           keyword_score=9, ctr_score=8, total_score=34)
        assert c.total_score == 34
        assert c.ctr_score == 8

    def test_chapter_model(self):
        from app.seo.schemas import Chapter
        ch = Chapter(time="1:30", label="Main content")
        assert ch.time == "1:30"
        assert ch.label == "Main content"


# ── SEO Generator tests ───────────────────────────────────────────────────────

class TestSEOGenerator:

    def _make_research(self):
        from app.research.schemas import ResearchResult, Fact
        return ResearchResult(
            topic="How black holes work",
            summary="Black holes are extreme gravitational objects.",
            facts=[
                Fact(fact="Black holes have an event horizon", confidence=0.99),
                Fact(fact="Hawking radiation causes slow evaporation", confidence=0.90),
            ],
        )

    def _make_script(self):
        from app.script.schemas import ScriptResult, ScriptSection
        return ScriptResult(
            title="How Black Holes Work",
            hook="Imagine a place where even light cannot escape...",
            sections=[
                ScriptSection(id=1, title="What Is a Black Hole?",
                              narration="Section 1 narration", duration_seconds=45),
                ScriptSection(id=2, title="How They Form",
                              narration="Section 2 narration", duration_seconds=50),
            ],
            conclusion="Black holes remain fascinating.",
            estimated_duration_seconds=300,
            word_count=600,
        )

    def test_generate_produces_valid_seo(self, tmp_path):
        _make_project("seo001")
        from app.seo.metadata_generator import SEOGenerator
        gen = SEOGenerator(project_id="seo001", llm=MockLLM([SEO_JSON]))
        result = gen.generate(
            topic="How black holes work",
            script=self._make_script(),
            research=self._make_research(),
        )
        assert result.best_title == "How Black Holes Work: Complete Guide"
        assert len(result.tags) == 20
        assert "black holes" in result.tags
        assert len(result.chapters) == 6

    def test_seo_persisted_to_db(self, tmp_path):
        _make_project("seo002")
        from app.seo.metadata_generator import SEOGenerator
        from app.database.models import Metadata
        from app.database.session import get_session
        gen = SEOGenerator(project_id="seo002", llm=MockLLM([SEO_JSON]))
        gen.generate(
            topic="How black holes work",
            script=self._make_script(),
            research=self._make_research(),
        )
        with get_session() as s:
            row = s.query(Metadata).filter_by(project_id="seo002").first()
            title = row.title
            tag_count = len(row.tags or [])
            chapter_count = len(row.chapters or [])
        assert title == "How Black Holes Work: Complete Guide"
        assert tag_count == 20
        assert chapter_count == 6

    def test_seo_resume_skips_llm(self, tmp_path):
        _make_project("seo003")
        from app.seo.metadata_generator import SEOGenerator
        gen = SEOGenerator(project_id="seo003", llm=MockLLM([SEO_JSON]))
        gen.generate("How black holes work", self._make_script(), self._make_research())
        # Second call with empty LLM — should load from DB
        gen2 = SEOGenerator(project_id="seo003", llm=MockLLM([]))
        result2 = gen2.generate("How black holes work", self._make_script(), self._make_research())
        assert result2.best_title == "How Black Holes Work: Complete Guide"

    def test_chapters_auto_built_from_script(self, tmp_path):
        _make_project("seo004")
        from app.seo.metadata_generator import SEOGenerator
        # Return SEO with no chapters — should inject from script
        seo_no_chapters = {**SEO_JSON, "chapters": []}
        gen = SEOGenerator(project_id="seo004", llm=MockLLM([seo_no_chapters]))
        result = gen.generate("How black holes work", self._make_script(), self._make_research())
        # Should have at least the Intro chapter
        assert len(result.chapters) >= 1
        assert result.chapters[0].label == "Intro"

    def test_cost_recorded(self, tmp_path):
        _make_project("seo005")
        from app.seo.metadata_generator import SEOGenerator
        from app.database.models import ApiCost
        from app.database.session import get_session
        gen = SEOGenerator(project_id="seo005", llm=MockLLM([SEO_JSON]))
        gen.generate("How black holes work", self._make_script(), self._make_research())
        with get_session() as s:
            ops = {r.operation for r in
                   s.query(ApiCost).filter_by(project_id="seo005").all()}
        assert "seo" in ops


# ── Thumbnail tests ───────────────────────────────────────────────────────────

class TestThumbnailGenerator:

    def _make_seo(self):
        from app.seo.schemas import SEOMetadata
        return SEOMetadata.model_validate(SEO_JSON)

    def test_renders_thumbnail_file(self, tmp_path):
        pytest.importorskip("PIL", reason="Pillow not installed")
        _make_project("thumb001")
        from app.thumbnail.generator import ThumbnailGenerator
        gen = ThumbnailGenerator(project_id="thumb001", llm=MockLLM([THUMBNAIL_JSON]))
        out_dir = tmp_path / "output" / "thumb001"
        out_dir.mkdir(parents=True)
        path = gen.generate(
            topic="How black holes work",
            seo=self._make_seo(),
            output_dir=out_dir,
        )
        assert path.exists()
        assert path.suffix == ".jpg"
        assert path.stat().st_size > 1000  # non-trivial file

    def test_thumbnail_size_correct(self, tmp_path):
        pytest.importorskip("PIL", reason="Pillow not installed")
        _make_project("thumb002")
        from PIL import Image
        from app.thumbnail.generator import ThumbnailGenerator
        gen = ThumbnailGenerator(project_id="thumb002", llm=MockLLM([THUMBNAIL_JSON]))
        out_dir = tmp_path / "output" / "thumb002"
        out_dir.mkdir(parents=True)
        path = gen.generate("How black holes work", self._make_seo(), out_dir)
        img = Image.open(path)
        assert img.size == (1280, 720)

    def test_thumbnail_resume_skips_render(self, tmp_path):
        pytest.importorskip("PIL", reason="Pillow not installed")
        _make_project("thumb003")
        from app.thumbnail.generator import ThumbnailGenerator
        out_dir = tmp_path / "output" / "thumb003"
        out_dir.mkdir(parents=True)
        # Pre-create thumbnail
        existing = out_dir / "thumbnail.jpg"
        existing.write_bytes(b"fake-jpeg-data")
        # LLM is empty — resume should skip
        gen = ThumbnailGenerator(project_id="thumb003", llm=MockLLM([]))
        path = gen.generate("How black holes work", self._make_seo(), out_dir)
        assert path == existing

    def test_fallback_concept_renders(self, tmp_path):
        pytest.importorskip("PIL", reason="Pillow not installed")
        _make_project("thumb004")
        from app.thumbnail.generator import ThumbnailGenerator, _fallback_concept, render_thumbnail
        concept = _fallback_concept("How black holes work", "How Black Holes Work: Complete Guide")
        out = tmp_path / "fallback_thumb.jpg"
        path = render_thumbnail(concept, out)
        assert path.exists()
        assert path.stat().st_size > 500

    def test_render_thumbnail_direct(self, tmp_path):
        pytest.importorskip("PIL", reason="Pillow not installed")
        from app.thumbnail.generator import render_thumbnail
        concept = {
            "background_color": "#1a1a2e",
            "background_color_2": "#16213e",
            "main_text": "TEST TITLE",
            "sub_text": "subtitle here",
            "text_color": "#ffffff",
            "accent_color": "#ff6b35",
        }
        out = tmp_path / "test_thumb.jpg"
        path = render_thumbnail(concept, out)
        assert path.exists()


# ── YouTube uploader tests (mocked) ──────────────────────────────────────────

class TestYouTubeUploader:

    def _make_seo(self):
        from app.seo.schemas import SEOMetadata
        return SEOMetadata.model_validate(SEO_JSON)

    def test_raises_without_credentials(self, tmp_path):
        _make_project("yt001")
        from app.youtube.uploader import YouTubeUploader
        uploader = YouTubeUploader(project_id="yt001")
        fake_video = tmp_path / "video.mp4"
        fake_video.write_bytes(b"fake")
        with pytest.raises(ValueError, match="credentials not configured"):
            uploader.upload(video_path=fake_video, metadata=self._make_seo())

    def test_raises_when_video_missing(self, tmp_path, monkeypatch):
        _make_project("yt002")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_id", "fake_id")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_secret", "fake_secret")
        from app.youtube.uploader import YouTubeUploader
        uploader = YouTubeUploader(project_id="yt002")
        with pytest.raises(FileNotFoundError):
            uploader.upload(
                video_path=tmp_path / "nonexistent.mp4",
                metadata=self._make_seo(),
            )

    def test_privacy_downgraded_when_auto_publish_false(self, tmp_path, monkeypatch):
        """When auto_publish=False, public privacy is downgraded to private."""
        _make_project("yt003")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_id", "fid")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_secret", "fsec")
        monkeypatch.setattr("app.config.settings.settings.auto_publish", False)

        fake_video = tmp_path / "video.mp4"
        fake_video.write_bytes(b"fake-mp4")

        from app.youtube.uploader import YouTubeUploader

        # Mock the entire YouTube service
        mock_service = MagicMock()
        mock_insert = MagicMock()
        mock_insert.next_chunk.return_value = (None, {"id": "abc123VIDEO"})
        mock_service.videos.return_value.insert.return_value = mock_insert
        mock_service.thumbnails.return_value.set.return_value.execute.return_value = {}

        uploader = YouTubeUploader(project_id="yt003")
        with patch.object(uploader, "_build_service", return_value=mock_service):
            result = uploader.upload(
                video_path=fake_video,
                metadata=self._make_seo(),
                privacy_status="public",  # requested public
            )

        # Should be downgraded to private
        assert result.privacy_status == "private"
        assert result.video_id == "abc123VIDEO"
        assert result.url == "https://www.youtube.com/watch?v=abc123VIDEO"

    def test_upload_returns_correct_result(self, tmp_path, monkeypatch):
        _make_project("yt004")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_id", "fid")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_secret", "fsec")
        monkeypatch.setattr("app.config.settings.settings.auto_publish", False)

        fake_video = tmp_path / "video.mp4"
        fake_video.write_bytes(b"fake-mp4")
        fake_thumb = tmp_path / "thumb.jpg"
        fake_thumb.write_bytes(b"fake-jpeg")

        from app.youtube.uploader import YouTubeUploader

        mock_service = MagicMock()
        mock_insert = MagicMock()
        mock_insert.next_chunk.return_value = (None, {"id": "XYZ999VIDEO"})
        mock_service.videos.return_value.insert.return_value = mock_insert
        mock_service.thumbnails.return_value.set.return_value.execute.return_value = {}

        uploader = YouTubeUploader(project_id="yt004")
        with patch.object(uploader, "_build_service", return_value=mock_service):
            result = uploader.upload(
                video_path=fake_video,
                metadata=self._make_seo(),
                thumbnail_path=fake_thumb,
                privacy_status="private",
            )

        assert result.video_id == "XYZ999VIDEO"
        assert result.url == "https://www.youtube.com/watch?v=XYZ999VIDEO"
        assert result.privacy_status == "private"
        assert result.thumbnail_uploaded is True

    def test_upload_persisted_to_db(self, tmp_path, monkeypatch):
        _make_project("yt005")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_id", "fid")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_secret", "fsec")
        monkeypatch.setattr("app.config.settings.settings.auto_publish", False)

        fake_video = tmp_path / "video.mp4"
        fake_video.write_bytes(b"x")

        from app.youtube.uploader import YouTubeUploader
        from app.database.models import YouTubeUpload
        from app.database.session import get_session

        mock_service = MagicMock()
        mock_insert = MagicMock()
        mock_insert.next_chunk.return_value = (None, {"id": "DB_VIDEO_001"})
        mock_service.videos.return_value.insert.return_value = mock_insert
        mock_service.thumbnails.return_value.set.return_value.execute.return_value = {}

        uploader = YouTubeUploader(project_id="yt005")
        with patch.object(uploader, "_build_service", return_value=mock_service):
            uploader.upload(fake_video, self._make_seo())

        with get_session() as s:
            row = s.query(YouTubeUpload).filter_by(project_id="yt005").first()
            vid = row.video_id if row else None
            privacy = row.privacy_status if row else None

        assert vid == "DB_VIDEO_001"
        assert privacy == "private"

    def test_resume_skips_second_upload(self, tmp_path, monkeypatch):
        _make_project("yt006")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_id", "fid")
        monkeypatch.setattr("app.config.settings.settings.youtube_client_secret", "fsec")
        monkeypatch.setattr("app.config.settings.settings.auto_publish", False)

        fake_video = tmp_path / "video.mp4"
        fake_video.write_bytes(b"x")

        call_count = {"n": 0}

        from app.youtube.uploader import YouTubeUploader

        mock_service = MagicMock()
        mock_insert = MagicMock()

        def counted_next_chunk():
            call_count["n"] += 1
            return None, {"id": "RESUME_VID"}

        mock_insert.next_chunk = counted_next_chunk
        mock_service.videos.return_value.insert.return_value = mock_insert

        uploader = YouTubeUploader(project_id="yt006")
        with patch.object(uploader, "_build_service", return_value=mock_service):
            r1 = uploader.upload(fake_video, self._make_seo())
            r2 = uploader.upload(fake_video, self._make_seo())

        assert r1.video_id == "RESUME_VID"
        assert r2.video_id == "RESUME_VID"
        assert call_count["n"] == 1  # only uploaded once


# ── Full pipeline with SEO + thumbnail ───────────────────────────────────────

class TestFullPipelineWithSEO:

    RESEARCH_JSON = {
        "topic": "How black holes work",
        "summary": "Black holes are extreme gravitational objects.",
        "facts": [{"fact": "Black holes have an event horizon", "confidence": 0.99}],
        "claims": [], "statistics": [], "dates": [], "people": [],
        "locations": [], "uncertain_claims": [],
    }
    SCRIPT_JSON = {
        "title": "How Black Holes Work",
        "hook": "Imagine a place where even light cannot escape...",
        "sections": [
            {"id": 1, "title": "What Is a Black Hole?",
             "narration": "A black hole is a region...", "duration_seconds": 45},
        ],
        "conclusion": "Black holes remain fascinating.",
        "call_to_action": "Subscribe for more!",
        "estimated_duration_seconds": 300, "word_count": 600, "tone": "documentary",
    }

    def test_orchestrator_runs_seo_and_thumbnail(self, tmp_path):
        pytest.importorskip("PIL", reason="Pillow not installed")
        from app.pipeline.orchestrator import Orchestrator
        from app.database.session import init_db

        init_db()
        llm = MockLLM([self.RESEARCH_JSON, self.SCRIPT_JSON, SEO_JSON, THUMBNAIL_JSON])
        orch = Orchestrator.__new__(Orchestrator)
        orch.llm = llm
        result = orch.run(topic="How black holes work")

        assert result.status == "complete"
        assert result.seo_title == "How Black Holes Work: Complete Guide"
        assert len(result.seo_tags) == 20
        assert result.thumbnail_path is not None
        assert result.thumbnail_path.exists()
        assert result.errors == []
        assert (result.output_dir / "seo.json").exists()
        assert (result.output_dir / "thumbnail.jpg").exists()

    def test_seo_json_saved_to_output(self, tmp_path):
        pytest.importorskip("PIL", reason="Pillow not installed")
        from app.pipeline.orchestrator import Orchestrator
        from app.database.session import init_db

        init_db()
        llm = MockLLM([self.RESEARCH_JSON, self.SCRIPT_JSON, SEO_JSON, THUMBNAIL_JSON])
        orch = Orchestrator.__new__(Orchestrator)
        orch.llm = llm
        result = orch.run(topic="How black holes work")

        seo_data = json.loads((result.output_dir / "seo.json").read_text())
        assert seo_data["best_title"] == "How Black Holes Work: Complete Guide"
        assert len(seo_data["tags"]) == 20
        assert seo_data["chapters"][0]["time"] == "0:00"
