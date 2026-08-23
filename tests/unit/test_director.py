from __future__ import annotations

from app.director.director import Director, ProductionGraph, VideoRequest


def test_production_graph_has_explicit_valid_dependencies():
    ProductionGraph.validate()
    names = [node.name for node in ProductionGraph.nodes]
    assert names[0] == "research"
    assert names[-2:] == ["quality", "youtube"]
    assert names.index("seo") < names.index("thumbnail")
    assert "seo" in next(node.dependencies for node in ProductionGraph.nodes if node.name == "thumbnail")
    assert "rendering" in next(node.dependencies for node in ProductionGraph.nodes if node.name == "quality")
    assert next(node.dependencies for node in ProductionGraph.nodes if node.name == "youtube") == ("quality",)


def test_natural_language_duration_is_inferred_when_selector_is_absent():
    request = VideoRequest.from_natural_language(
        "Create a 20-minute cinematic documentary about Muthappa Rai"
    )
    assert request.duration_seconds == 1200
    assert request.style == "Cinematic Documentary"


def test_explicit_duration_overrides_prompt_hint():
    request = VideoRequest.from_natural_language(
        "Create a 20-minute documentary", duration_seconds=60,
    )
    assert request.duration_seconds == 60


def test_director_errors_are_safe_for_default_ui():
    message = Director._friendly_error("rendering", RuntimeError("secret stack trace"))
    assert message == "Rendering failed after automatic retries."
    assert "secret" not in message


def test_director_persists_producing_before_provider_initialization(tmp_path, monkeypatch):
    request = VideoRequest("Create a short local documentary")
    director = Director("job-local", "project-local", request)
    director.output_dir = tmp_path
    director.state_path = tmp_path / director.state_filename
    monkeypatch.setattr(director, "_project_status", lambda status: None)
    monkeypatch.setattr("app.llm.factory.get_llm_provider", lambda *args: (_ for _ in ()).throw(ValueError("missing provider")))
    monkeypatch.setattr("app.director.director.settings.zero_cost_mode", False)

    state = director.execute()

    assert state["state"] == "REQUIRES_ATTENTION"
    assert director.state_path.exists()


def test_stage_retry_skips_completed_upstream_directors(tmp_path, monkeypatch):
    monkeypatch.setattr("app.director.director.settings.output_dir", tmp_path)
    request = VideoRequest("Create a short local documentary")
    initial = Director("old-job", "resume-project", request)
    for stage in ("research", "story", "script", "voice", "timeline", "characters"):
        initial.state["stages"][stage]["status"] = "complete"
    initial.state["stages"]["visuals"]["status"] = "failed"
    initial.state_path.write_text(__import__("json").dumps(initial.state), encoding="utf-8")

    calls = []

    class Worker:
        def __init__(self, name):
            self.name = name
        def run(self, context):
            calls.append(self.name)
            return {"score": 100} if self.name == "quality" else {}

    resumed = Director("retry-job", "resume-project", request, resume_stage="visuals")
    monkeypatch.setattr(resumed, "_project_status", lambda status: None)
    monkeypatch.setattr(
        resumed, "_directors",
        lambda llm: {
            node.name: Worker(node.name)
            for node in ProductionGraph.nodes if node.name != "youtube"
        },
    )
    monkeypatch.setattr("app.llm.factory.get_llm_provider", lambda *args: object())

    state = resumed.execute()

    assert calls[0] == "visuals"
    assert not {"research", "story", "script", "voice", "timeline", "characters"} & set(calls)
    assert state["state"] == "VIDEO_READY"


def test_stage_retry_includes_pending_dependency_before_failed_stage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.director.director.settings.output_dir", tmp_path)
    request = VideoRequest("Create a short local documentary")
    initial = Director("old-job", "dependency-project", request)
    for stage in (
        "research", "story", "script", "voice", "timeline", "characters",
        "visuals", "shots", "animation", "sound", "music", "rendering", "subtitles",
    ):
        initial.state["stages"][stage]["status"] = "complete"
    initial.state["stages"]["seo"]["status"] = "pending"
    initial.state["stages"]["thumbnail"]["status"] = "failed"
    initial.state_path.write_text(__import__("json").dumps(initial.state), encoding="utf-8")

    calls = []

    class Worker:
        def __init__(self, name):
            self.name = name

        def run(self, context):
            calls.append(self.name)
            return {"score": 100} if self.name == "quality" else {}

    resumed = Director("retry-job", "dependency-project", request, resume_stage="thumbnail")
    monkeypatch.setattr(resumed, "_project_status", lambda status: None)
    monkeypatch.setattr(
        resumed, "_directors",
        lambda llm: {
            node.name: Worker(node.name)
            for node in ProductionGraph.nodes if node.name != "youtube"
        },
    )
    monkeypatch.setattr("app.llm.factory.get_llm_provider", lambda *args: object())

    state = resumed.execute()

    assert calls[:2] == ["seo", "thumbnail"]
    assert state["state"] == "VIDEO_READY"
