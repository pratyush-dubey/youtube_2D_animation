"""
Unit tests for script Pydantic schema validation.
"""
from __future__ import annotations

import pytest
from app.script.schemas import ScriptResult, ScriptSection


class TestScriptSection:
    def test_valid(self):
        s = ScriptSection(id=1, narration="Hello world", duration_seconds=30.0)
        assert s.id == 1
        assert s.duration_seconds == 30.0

    def test_duration_coerced_from_string(self):
        s = ScriptSection(id=1, narration="x", duration_seconds="45")
        assert s.duration_seconds == 45.0

    def test_invalid_duration_falls_back(self):
        s = ScriptSection(id=1, narration="x", duration_seconds="bad")
        assert s.duration_seconds == 30.0


class TestScriptResult:
    def test_valid_minimal(self):
        r = ScriptResult(title="Test", hook="Grab attention")
        assert r.title == "Test"
        assert r.sections == []

    def test_full_narration(self):
        r = ScriptResult(
            title="Test",
            hook="Hook text",
            sections=[ScriptSection(id=1, narration="Section 1", duration_seconds=30)],
            conclusion="Bye",
            call_to_action="Subscribe",
        )
        full = r.full_narration()
        assert "Hook text" in full
        assert "Section 1" in full
        assert "Bye" in full
        assert "Subscribe" in full

    def test_duration_coerced_from_string(self):
        r = ScriptResult(title="T", hook="H", estimated_duration_seconds="300")
        assert r.estimated_duration_seconds == 300

    def test_duration_falls_back_on_bad_value(self):
        r = ScriptResult(title="T", hook="H", estimated_duration_seconds="bad")
        assert r.estimated_duration_seconds == 480
