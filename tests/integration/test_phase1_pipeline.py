"""
Integration tests for the full Phase 1 pipeline.

These tests run the entire research → script pipeline using a mock LLM
that returns pre-crafted JSON responses. No real network calls are made.
No Ollama, OpenAI, or Gemini required.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, Project

# ── Shared DB fixture ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Use an isolated in-memory SQLite DB for every test."""
    db_file = tmp_path / "test.sqlite3"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    import app.database.session as db_mod
    monkeypatch.setattr(db_mod, "engine", test_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSession)

    # Also redirect output/project dirs to tmp
    monkeypatch.setattr("app.config.settings.settings.output_dir", tmp_path / "output")
    monkeypatch.setattr("app.config.settings.settings.project_dir", tmp_path / "projects")
    (tmp_path / "output").mkdir()
    (tmp_path / "projects").mkdir()
    yield


# ── Mock LLM responses ────────────────────────────────────────────────────────

RESEARCH_JSON = {
    "topic": "How black holes work",
    "summary": "Black holes are regions of spacetime where gravity is so strong nothing can escape.",
    "facts": [
        {"fact": "Black holes have an event horizon", "confidence": 0.99},
        {"fact": "Hawking radiation causes black holes to slowly evaporate", "confidence": 0.90},
    ],
    "claims": [
        {"claim": "The first black hole image was captured in 2019", "source": "EHT", "confidence": 0.99}
    ],
    "statistics": [
        {"stat": "Stellar black holes typically have masses 5-100x the Sun", "source": "NASA", "confidence": 0.95}
    ],
    "dates": [
        {"event": "First black hole image", "date": "April 10, 2019", "confidence": 1.0}
    ],
    "people": [
        {"name": "Stephen Hawking", "role": "Proposed Hawking radiation"},
        {"name": "Katie Bouman", "role": "Led algorithm development for first black hole image"},
    ],
    "locations": [
        {"name": "M87 galaxy", "relevance": "Location of the first photographed black hole"}
    ],
    "uncertain_claims": [
        {"claim": "Black holes may be portals to other universes", "note": "Speculative theory, no evidence"}
    ],
    "key_questions": [
        "What happens at the singularity?",
        "Do black holes destroy information?"
    ],
    "suggested_sections": [
        "What is a black hole?",
        "How are black holes formed?",
        "The event horizon",
        "Hawking radiation",
        "The first image of a black hole",
    ],
}

SCRIPT_JSON = {
    "title": "How Black Holes Work: The Most Extreme Objects in the Universe",
    "hook": "Imagine a place in space so dense that even light cannot escape. A place where time slows to a crawl and matter is crushed into infinite density. That place is real — and it's called a black hole.",
    "sections": [
        {
            "id": 1,
            "title": "What Is a Black Hole?",
            "narration": "A black hole is a region of spacetime where gravity is so intense that nothing — not even light — can escape once it crosses the event horizon.",
            "duration_seconds": 45,
            "key_facts": ["Black holes have an event horizon"],
        },
        {
            "id": 2,
            "title": "How Are Black Holes Formed?",
            "narration": "Most black holes form when massive stars — those at least 20 times more massive than our Sun — reach the end of their lives and collapse under their own gravity in a violent supernova explosion.",
            "duration_seconds": 50,
            "key_facts": ["Stellar black holes typically have masses 5-100x the Sun"],
        },
        {
            "id": 3,
            "title": "The Event Horizon",
            "narration": "The event horizon is the point of no return. It is not a physical surface but rather a mathematical boundary. Cross it, and you can never come back — not even information can escape.",
            "duration_seconds": 40,
            "key_facts": ["Black holes have an event horizon"],
        },
        {
            "id": 4,
            "title": "Hawking Radiation",
            "narration": "In 1974, physicist Stephen Hawking proposed that black holes are not completely black. Due to quantum effects near the event horizon, they slowly emit radiation — now called Hawking radiation — and gradually evaporate over astronomical timescales.",
            "duration_seconds": 55,
            "key_facts": ["Hawking radiation causes black holes to slowly evaporate"],
        },
        {
            "id": 5,
            "title": "The First Black Hole Image",
            "narration": "For decades, black holes were purely theoretical. Then on April 10, 2019, the Event Horizon Telescope collaboration released the first direct image of a black hole — the supermassive black hole at the center of galaxy M87.",
            "duration_seconds": 50,
            "key_facts": ["The first black hole image was captured in 2019"],
        },
    ],
    "conclusion": "Black holes remain one of the most fascinating and extreme objects in the universe. They bend space, slow time, and challenge our deepest understanding of physics. And somehow, the more we learn, the more mysterious they become.",
    "call_to_action": "If you found this video fascinating, hit subscribe — we cover the strangest and most mind-bending topics in science every week.",
    "estimated_duration_seconds": 480,
    "word_count": 1040,
    "tone": "documentary",
}


class MockLLMProvider:
    """
    Deterministic mock LLM that cycles through pre-set responses.
    Used for integration tests — no network required.
    """
    provider_name = "mock"
    model = "mock-model"

    def __init__(self, responses: list[dict]):
        self._responses = iter(responses)

    def generate_json(self, prompt: str, schema_hint: str = "", **kwargs):
        from app.llm.base import LLMResponse
        data = next(self._responses)
        resp = LLMResponse(
            content=json.dumps(data),
            input_tokens=len(prompt) // 4,
            output_tokens=len(json.dumps(data)) // 4,
            model=self.model,
            provider=self.provider_name,
        )
        return data, resp

    def generate(self, prompt: str, **kwargs):
        from app.llm.base import LLMResponse
        return LLMResponse(content="", input_tokens=0, output_tokens=0,
                           model=self.model, provider=self.provider_name)


# ── Integration tests ─────────────────────────────────────────────────────────

class TestFullPipelinePhase1:

    def _make_mock_llm(self):
        return MockLLMProvider([RESEARCH_JSON, SCRIPT_JSON])

    def test_research_stage_produces_valid_result(self, tmp_path):
        from app.database.session import get_session
        from app.database.models import Project as ProjModel
        from app.research.researcher import Researcher

        project_id = "integ001"
        with get_session() as s:
            s.add(ProjModel(id=project_id, topic="How black holes work"))

        researcher = Researcher(project_id=project_id, llm=self._make_mock_llm())
        result = researcher.run(topic="How black holes work", language="English")

        assert result.topic == "How black holes work"
        assert len(result.facts) == 2
        assert result.facts[0].fact == "Black holes have an event horizon"
        assert result.facts[0].confidence == 0.99
        assert len(result.claims) == 1
        assert len(result.people) == 2
        assert len(result.uncertain_claims) == 1

    def test_research_persisted_to_db(self, tmp_path):
        from app.database.session import get_session
        from app.database.models import Project as ProjModel, Research, Source
        from app.research.researcher import Researcher

        project_id = "integ002"
        with get_session() as s:
            s.add(ProjModel(id=project_id, topic="How black holes work"))

        researcher = Researcher(project_id=project_id, llm=self._make_mock_llm())
        researcher.run(topic="How black holes work", language="English")

        with get_session() as s:
            row = s.query(Research).filter_by(project_id=project_id).first()
            assert row is not None
            assert len(row.facts) == 2
            assert row.raw_text == "How black holes work"
            sources = s.query(Source).filter_by(project_id=project_id).all()
            assert len(sources) == 1
            assert sources[0].title == "LLM Training Knowledge"

    def test_research_resume_skips_llm(self, tmp_path):
        from app.database.session import get_session
        from app.database.models import Project as ProjModel
        from app.research.researcher import Researcher

        project_id = "integ003"
        with get_session() as s:
            s.add(ProjModel(id=project_id, topic="How black holes work"))

        llm = self._make_mock_llm()
        r1 = Researcher(project_id=project_id, llm=llm)
        r1.run(topic="How black holes work")

        # Second run — LLM iterator is exhausted, but resume should not call it
        r2 = Researcher(project_id=project_id, llm=MockLLMProvider([]))
        result = r2.run(topic="How black holes work")
        assert len(result.facts) == 2  # loaded from DB

    def test_script_stage_produces_valid_result(self, tmp_path):
        from app.database.session import get_session
        from app.database.models import Project as ProjModel
        from app.research.schemas import ResearchResult, Fact, Claim
        from app.script.script_generator import ScriptGenerator

        project_id = "integ004"
        with get_session() as s:
            s.add(ProjModel(id=project_id, topic="How black holes work"))

        research = ResearchResult.model_validate(RESEARCH_JSON)
        llm = MockLLMProvider([SCRIPT_JSON])
        gen = ScriptGenerator(project_id=project_id, llm=llm)
        result = gen.generate(
            topic="How black holes work",
            research=research,
            target_duration_seconds=480,
        )

        assert result.title == "How Black Holes Work: The Most Extreme Objects in the Universe"
        assert len(result.sections) == 5
        assert result.estimated_duration_seconds == 124
        assert result.word_count == 268
        assert result.hook.startswith("Imagine")

    def test_script_sections_persisted_as_scenes(self, tmp_path):
        from app.database.session import get_session
        from app.database.models import Project as ProjModel, Scene, Script as ScriptModel
        from app.research.schemas import ResearchResult
        from app.script.script_generator import ScriptGenerator

        project_id = "integ005"
        with get_session() as s:
            s.add(ProjModel(id=project_id, topic="How black holes work"))

        research = ResearchResult.model_validate(RESEARCH_JSON)
        gen = ScriptGenerator(project_id=project_id, llm=MockLLMProvider([SCRIPT_JSON]))
        gen.generate(topic="How black holes work", research=research)

        with get_session() as s:
            script = s.query(ScriptModel).filter_by(project_id=project_id).first()
            assert script is not None
            assert script.title == SCRIPT_JSON["title"]
            scenes = s.query(Scene).filter_by(project_id=project_id).all()
            assert len(scenes) == 5
            assert scenes[0].scene_order == 1
            assert scenes[0].narration == SCRIPT_JSON["sections"][0]["narration"]

    def test_full_orchestrator_pipeline(self, tmp_path, monkeypatch):
        from app.pipeline.orchestrator import Orchestrator
        from app.pipeline.state import PipelineState

        llm = MockLLMProvider([RESEARCH_JSON, SCRIPT_JSON])
        orch = Orchestrator.__new__(Orchestrator)
        orch.llm = llm

        from app.database.session import init_db
        init_db()

        result = orch.run(
            topic="How black holes work",
            language="English",
            target_duration_seconds=480,
        )

        assert result.status == "complete"
        assert result.script_title == SCRIPT_JSON["title"]
        assert result.script_sections == 5
        assert result.estimated_duration_seconds == 124
        # SEO/thumbnail are soft stages — they may fail without aborting the pipeline
        # so errors can contain non-fatal warnings
        fatal_errors = [e for e in result.errors if "(non-fatal)" not in e]
        assert fatal_errors == []

        # Output files exist
        assert (result.output_dir / "research.json").exists()
        assert (result.output_dir / "script.json").exists()

        # Research JSON is valid
        research_data = json.loads((result.output_dir / "research.json").read_text())
        assert research_data["topic"] == "How black holes work"
        assert len(research_data["facts"]) == 2

        # Script JSON is valid
        script_data = json.loads((result.output_dir / "script.json").read_text())
        assert script_data["title"] == SCRIPT_JSON["title"]

    def test_pipeline_state_complete_after_success(self, tmp_path):
        from app.pipeline.orchestrator import Orchestrator
        from app.pipeline.state import PipelineState, STATUS_COMPLETE
        from app.database.session import init_db

        init_db()
        llm = MockLLMProvider([RESEARCH_JSON, SCRIPT_JSON])
        orch = Orchestrator.__new__(Orchestrator)
        orch.llm = llm
        result = orch.run(topic="How black holes work")

        state = PipelineState(result.project_id)
        summary = state.get_summary()
        assert summary["research"] == STATUS_COMPLETE
        assert summary["script"] == STATUS_COMPLETE
        assert summary["storyboard"] == "pending"  # not yet implemented

    def test_pipeline_resumes_after_research_complete(self, tmp_path):
        from app.pipeline.orchestrator import Orchestrator
        from app.database.session import init_db

        init_db()
        # First run: research only (script LLM will fail after exhaustion)
        llm1 = MockLLMProvider([RESEARCH_JSON, SCRIPT_JSON])
        orch1 = Orchestrator.__new__(Orchestrator)
        orch1.llm = llm1
        result1 = orch1.run(topic="How black holes work")
        assert result1.status == "complete"
        project_id = result1.project_id

        # Second run with same project_id: both stages already complete, should skip both
        llm2 = MockLLMProvider([])  # no responses — if LLM is called, it will crash
        orch2 = Orchestrator.__new__(Orchestrator)
        orch2.llm = llm2
        result2 = orch2.run(topic="How black holes work", project_id=project_id)

        assert result2.status == "complete"
        fatal2 = [e for e in result2.errors if "(non-fatal)" not in e]
        assert fatal2 == []

    def test_cost_recorded_for_mock_provider(self, tmp_path):
        from app.pipeline.orchestrator import Orchestrator
        from app.database.session import init_db, get_session
        from app.database.models import ApiCost

        init_db()
        llm = MockLLMProvider([RESEARCH_JSON, SCRIPT_JSON])
        orch = Orchestrator.__new__(Orchestrator)
        orch.llm = llm
        result = orch.run(topic="How black holes work")

        with get_session() as s:
            costs = s.query(ApiCost).filter_by(project_id=result.project_id).all()
            # Access all attributes inside the session — ORM expires them on close
            count = len(costs)
            operations = {c.operation for c in costs}

        assert count == 2  # one for research, one for script
        assert "research" in operations
        assert "script" in operations


class TestResearchSchemaEdgeCases:

    def test_missing_optional_fields_ok(self):
        from app.research.schemas import ResearchResult
        r = ResearchResult.model_validate({
            "topic": "test topic",
            # All optional fields omitted
        })
        assert r.facts == []
        assert r.uncertain_claims == []
        assert r.suggested_sections == []

    def test_all_list_fields_accept_none(self):
        from app.research.schemas import ResearchResult
        r = ResearchResult.model_validate({
            "topic": "t",
            "facts": None,
            "claims": None,
            "statistics": None,
        })
        assert r.facts == []
        assert r.claims == []
        assert r.statistics == []

    def test_confidence_clamped(self):
        from app.research.schemas import Fact
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            Fact(fact="x", confidence=1.5)
        with pytest.raises(pydantic.ValidationError):
            Fact(fact="x", confidence=-0.1)

    def test_fact_default_confidence(self):
        from app.research.schemas import Fact
        f = Fact(fact="gravity bends light")
        assert 0.0 <= f.confidence <= 1.0


class TestScriptSchemaEdgeCases:

    def test_empty_sections_list(self):
        from app.script.schemas import ScriptResult
        r = ScriptResult(title="T", hook="H", sections=[])
        assert r.full_narration() == "H"

    def test_full_narration_omits_empty_parts(self):
        from app.script.schemas import ScriptResult, ScriptSection
        r = ScriptResult(
            title="T",
            hook="Hook",
            sections=[ScriptSection(id=1, narration="Sec1", duration_seconds=30)],
            conclusion="",   # empty — should be omitted
            call_to_action="CTA",
        )
        full = r.full_narration()
        assert "Hook" in full
        assert "Sec1" in full
        assert "CTA" in full
        assert full.count("\n\n") == 2  # Hook↔Sec1, Sec1↔CTA

    def test_section_key_facts_default_empty(self):
        from app.script.schemas import ScriptSection
        s = ScriptSection(id=1, narration="text", duration_seconds=10)
        assert s.key_facts == []


class TestLLMJsonExtraction:

    def test_nested_json_extracted(self):
        from app.llm.base import _extract_json
        text = 'Sure! Here is the result:\n```json\n{"a": {"b": [1,2,3]}}\n```\nDone.'
        result = _extract_json(text)
        assert result == {"a": {"b": [1, 2, 3]}}

    def test_json_with_unicode(self):
        from app.llm.base import _extract_json
        payload = '{"title": "Black holes \u2014 the facts"}'
        assert _extract_json(payload) == {"title": "Black holes \u2014 the facts"}

    def test_first_json_block_wins(self):
        from app.llm.base import _extract_json
        # Two JSON objects in text — should get the outermost one
        text = '{"key": "val1", "nested": {"inner": "val2"}}'
        result = _extract_json(text)
        assert result["key"] == "val1"

    def test_returns_none_on_array(self):
        # Top-level JSON array should not be returned as dict
        from app.llm.base import _extract_json
        result = _extract_json('[1, 2, 3]')
        assert result is None


class TestPromptTemplateRendering:
    """Verify that prompt files render correctly without KeyError."""

    def test_research_prompt_renders(self):
        from app.config.settings import settings
        template = (settings.prompt_dir / "research_prompt.txt").read_text(encoding="utf-8")
        rendered = template.replace("{topic}", "test topic").replace("{language}", "English")
        assert "test topic" in rendered
        assert "{topic}" not in rendered
        assert "{language}" not in rendered

    def test_script_prompt_renders(self):
        from app.config.settings import settings
        template = (settings.prompt_dir / "script_prompt.txt").read_text(encoding="utf-8")
        rendered = (
            template
            .replace("{topic}", "test")
            .replace("{language}", "English")
            .replace("{style}", "documentary")
            .replace("{target_duration_minutes}", "8.0")
            .replace("{target_words}", "1040")
            .replace("{research_json}", "{}")
        )
        assert "test" in rendered
        assert "{topic}" not in rendered

    def test_storyboard_prompt_renders(self):
        from app.config.settings import settings
        template = (settings.prompt_dir / "storyboard_prompt.txt").read_text(encoding="utf-8")
        rendered = (
            template
            .replace("{topic}", "test")
            .replace("{style}", "documentary")
            .replace("{aspect_ratio}", "16:9")
            .replace("{script_json}", "{}")
        )
        assert "test" in rendered
        assert "{topic}" not in rendered


class TestCLICommands:

    def test_cli_help(self):
        from click.testing import CliRunner
        from app.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "create" in result.output

    def test_create_help(self):
        from click.testing import CliRunner
        from app.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["create", "--help"])
        assert result.exit_code == 0
        assert "--topic" in result.output
        assert "--provider" in result.output

    def test_status_help(self):
        from click.testing import CliRunner
        from app.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "--project" in result.output

    def test_create_missing_topic_fails(self):
        from click.testing import CliRunner
        from app.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["create"])
        assert result.exit_code != 0
        assert "topic" in result.output.lower() or "missing" in result.output.lower()

    def test_create_with_mock_llm(self, tmp_path, monkeypatch):
        """Full CLI create command with mock LLM — no network calls."""
        from click.testing import CliRunner
        from app.main import cli
        from app.database.session import init_db
        init_db()

        responses = [RESEARCH_JSON, SCRIPT_JSON]

        def mock_get_llm_provider(override=None):
            return MockLLMProvider(iter(responses))

        monkeypatch.setattr("app.pipeline.orchestrator.get_llm_provider", mock_get_llm_provider)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "create",
            "--topic", "How black holes work",
            "--output-json",
        ])

        assert result.exit_code == 0, f"exit={result.exit_code}\n{result.output}"
        # Find the first complete JSON object in output
        data = None
        for line in result.output.strip().split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        # If no single-line JSON, try parsing the whole output block
        if data is None:
            start = result.output.find("{")
            end = result.output.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(result.output[start:end])
        assert data is not None, f"No JSON found in output:\n{result.output}"
        assert data["status"] == "complete"
        # SEO/thumbnail soft failures are non-fatal — check only hard errors
        fatal = [e for e in data.get("errors", []) if "(non-fatal)" not in e]
        assert fatal == []
