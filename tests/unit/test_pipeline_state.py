"""
Unit tests for pipeline state machine.
Uses a temporary SQLite database so tests don't touch the real project DB.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, Project


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """
    Override the database engine to use a temporary SQLite file for each test.
    """
    db_file = tmp_path / "test.sqlite3"
    db_url = f"sqlite:///{db_file}"

    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)

    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    # Patch the session factory used by the app
    import app.database.session as db_module
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    yield


def _make_project(project_id: str = "test0001") -> None:
    from app.database.session import get_session
    with get_session() as session:
        session.add(Project(id=project_id, topic="Test topic"))


class TestPipelineState:
    def test_initial_state_all_pending(self):
        _make_project("p001")
        from app.pipeline.state import PipelineState, PIPELINE_STAGES, STATUS_PENDING
        state = PipelineState("p001")
        summary = state.get_summary()
        for stage in PIPELINE_STAGES:
            assert summary[stage] == STATUS_PENDING

    def test_should_run_pending_stage(self):
        _make_project("p002")
        from app.pipeline.state import PipelineState
        state = PipelineState("p002")
        assert state.should_run("research") is True

    def test_should_not_run_completed_stage(self):
        _make_project("p003")
        from app.pipeline.state import PipelineState
        state = PipelineState("p003")
        state.start("research")
        state.complete("research", output_data={"facts": 5})
        assert state.should_run("research") is False

    def test_fail_records_error(self):
        _make_project("p004")
        from app.pipeline.state import PipelineState, STATUS_FAILED
        state = PipelineState("p004")
        state.start("research")
        state.fail("research", "Connection refused")
        summary = state.get_summary()
        assert summary["research"] == STATUS_FAILED

    def test_output_data_persisted(self):
        _make_project("p005")
        from app.pipeline.state import PipelineState
        state = PipelineState("p005")
        state.start("script")
        state.complete("script", output_data={"title": "Hello"})
        output = state.get_output("script")
        assert output == {"title": "Hello"}

    def test_retry_count_increments(self):
        _make_project("p006")
        from app.pipeline.state import PipelineState
        state = PipelineState("p006")
        assert state.increment_retry("research") == 1
        assert state.increment_retry("research") == 2
