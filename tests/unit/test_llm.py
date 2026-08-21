"""
Unit tests for LLM provider abstraction.
These tests run without any external API — they mock the _call() method.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from app.llm.base import LLMProvider, LLMResponse, _extract_json
from app.llm.factory import get_llm_provider


# ── _extract_json ──────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_direct_json(self):
        assert _extract_json('{"key": "value"}') == {"key": "value"}

    def test_json_in_code_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert _extract_json(text) == {"key": "value"}

    def test_json_in_plain_fence(self):
        text = '```\n{"key": "value"}\n```'
        assert _extract_json(text) == {"key": "value"}

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"key": "value"} — done'
        assert _extract_json(text) == {"key": "value"}

    def test_invalid_returns_none(self):
        assert _extract_json("this is not json at all") is None

    def test_empty_string_returns_none(self):
        assert _extract_json("") is None


# ── LLMProvider retry logic ────────────────────────────────────────────────────

class _FakeProvider(LLMProvider):
    provider_name = "fake"

    def __init__(self, responses):
        self._responses = iter(responses)

    def _call(self, prompt, **kwargs):
        resp = next(self._responses)
        if isinstance(resp, Exception):
            raise resp
        return resp


class TestLLMProviderRetry:
    def test_succeeds_on_first_try(self):
        expected = LLMResponse(content="hello", provider="fake", model="test")
        provider = _FakeProvider([expected])
        result = provider.generate("test prompt", max_retries=3)
        assert result.content == "hello"

    def test_retries_on_failure_then_succeeds(self):
        good = LLMResponse(content="ok", provider="fake", model="test")
        provider = _FakeProvider([RuntimeError("network"), good])
        result = provider.generate("prompt", max_retries=3)
        assert result.content == "ok"

    def test_raises_after_max_retries(self):
        provider = _FakeProvider([RuntimeError("fail")] * 5)
        with pytest.raises(RuntimeError, match="failed after"):
            provider.generate("prompt", max_retries=3)

    def test_generate_json_parses_cleanly(self):
        payload = json.dumps({"result": 42})
        good = LLMResponse(content=payload, provider="fake", model="test")
        provider = _FakeProvider([good])
        result, resp = provider.generate_json("prompt")
        assert result == {"result": 42}
        assert resp.content == payload

    def test_generate_json_retries_on_bad_json(self):
        bad = LLMResponse(content="not json", provider="fake", model="test")
        good = LLMResponse(content='{"result": 42}', provider="fake", model="test")
        # Two bad attempts, then one good
        provider = _FakeProvider([bad, bad, good])
        result, resp = provider.generate_json("prompt")
        assert result["result"] == 42


# ── factory ────────────────────────────────────────────────────────────────────

class TestFactory:
    def test_ollama_provider_returned(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        # reload settings after env change
        from importlib import reload
        import app.config.settings as s_mod
        reload(s_mod)
        import app.llm.factory as f_mod
        reload(f_mod)
        from app.llm.factory import get_llm_provider as gp
        from app.llm.ollama_provider import OllamaProvider
        provider = gp("ollama")
        assert isinstance(provider, OllamaProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_provider("nonexistent")
