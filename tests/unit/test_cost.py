"""
Unit tests for cost tracker.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, Project


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.sqlite3"
    test_engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    import app.database.session as db_module
    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    # create a project row to satisfy FK
    from app.database.session import get_session
    with get_session() as s:
        s.add(Project(id="cost001", topic="test"))

    yield


class TestCostTracker:
    def test_local_provider_zero_cost(self):
        from app.cost.tracker import CostTracker
        tracker = CostTracker("cost001")
        cost = tracker.record("ollama", "llama3.1:8b", "research", 1000, 500)
        assert cost == 0.0
        assert tracker.total() == 0.0

    def test_openai_cost_estimated(self):
        from app.cost.tracker import CostTracker
        tracker = CostTracker("cost001")
        cost = tracker.record("openai", "gpt-4o-mini", "script", 2000, 1000)
        # gpt-4o-mini: $0.00015/1K input, $0.0006/1K output
        expected = round((2000 / 1000) * 0.00015 + (1000 / 1000) * 0.0006, 6)
        assert abs(cost - expected) < 1e-9

    def test_total_accumulates(self):
        from app.cost.tracker import CostTracker
        tracker = CostTracker("cost001")
        tracker.record("openai", "gpt-4o-mini", "research", 1000, 500)
        tracker.record("openai", "gpt-4o-mini", "script", 1000, 500)
        total = tracker.total()
        assert total > 0
        # Each call: (1000/1000)*0.00015 + (500/1000)*0.0006 = 0.00015 + 0.0003 = 0.00045
        expected_each = round((1000 / 1000) * 0.00015 + (500 / 1000) * 0.0006, 6)
        assert abs(total - 2 * expected_each) < 1e-6
