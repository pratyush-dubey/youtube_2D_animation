from __future__ import annotations

from app.agents.base import is_retryable_exception
from app.agents.storyboard_agent import (
    _deterministic_storyboard,
    _fit_storyboard_duration,
    _prepare_scenes,
)
from app.director.director import Director, VideoRequest, VisualDirector
from app.script.schemas import ScriptResult, ScriptSection


def test_retry_classifier_stops_quota_loops_but_retries_timeouts():
    assert not is_retryable_exception(RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
    assert is_retryable_exception(TimeoutError("read timed out"))


def test_local_storyboard_preserves_narration_and_target_duration():
    script = ScriptResult(
        title="Test",
        hook="A concise opening hook.",
        sections=[
            ScriptSection(id=1, title="Body", narration="The complete factual body remains intact for narration.", duration_seconds=40),
        ],
        conclusion="A clear conclusion follows.",
        call_to_action="Subscribe for more.",
        word_count=19,
        estimated_duration_seconds=30,
    )
    scenes = _prepare_scenes(_deterministic_storyboard(script, "Test topic"))
    scenes = _fit_storyboard_duration(scenes, 30)

    assert " ".join(scene["narration"] for scene in scenes).split() == script.full_narration().split()
    assert sum(scene["duration_seconds"] for scene in scenes) == 30


def test_director_injects_job_id_into_visual_director(tmp_path, monkeypatch):
    monkeypatch.setattr("app.director.director.settings.output_dir", tmp_path)
    director = Director("job-123", "project-123", VideoRequest("test"))
    workers = director._directors(object())

    assert isinstance(workers["visuals"], VisualDirector)
    assert workers["visuals"].job_id == "job-123"
