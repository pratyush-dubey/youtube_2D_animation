"""FallbackLLMProvider: primary succeeds -> used as-is; primary raises -> falls
back to the secondary provider instead of failing the call."""
from __future__ import annotations

import pytest

from app.llm.base import LLMProvider, LLMResponse
from app.llm.fallback_provider import FallbackLLMProvider


class _StubProvider(LLMProvider):
    def __init__(self, provider_name: str, model: str = "stub-model", fail: bool = False):
        self.provider_name = provider_name
        self.model = model
        self.fail = fail
        self.calls = 0

    def _call(self, prompt: str, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated provider outage")
        return LLMResponse(content="ok", model=self.model, provider=self.provider_name)


def test_primary_success_never_touches_fallback():
    primary = _StubProvider("gemini")
    fallback = _StubProvider("ollama")
    llm = FallbackLLMProvider(lambda: primary, lambda: fallback, "gemini", "ollama")

    response = llm.generate("hi", max_retries=1)

    assert response.provider == "gemini"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert llm.provider_name == "gemini"


def test_primary_failure_falls_back_to_secondary():
    primary = _StubProvider("gemini", fail=True)
    fallback = _StubProvider("ollama")
    llm = FallbackLLMProvider(lambda: primary, lambda: fallback, "gemini", "ollama")

    response = llm.generate("hi", max_retries=1)

    assert response.provider == "ollama"
    assert fallback.calls == 1
    assert llm.provider_name == "ollama"


def test_both_providers_failing_raises():
    primary = _StubProvider("gemini", fail=True)
    fallback = _StubProvider("ollama", fail=True)
    llm = FallbackLLMProvider(lambda: primary, lambda: fallback, "gemini", "ollama")

    with pytest.raises(RuntimeError):
        llm.generate("hi", max_retries=1)
