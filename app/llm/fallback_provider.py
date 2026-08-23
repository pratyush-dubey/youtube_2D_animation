"""Primary/fallback LLM provider composition.

Wraps two providers so an outage of the primary (invalid/rate-limited API
key, network failure, missing SDK) degrades to the fallback instead of
failing the whole pipeline stage. Both providers are constructed lazily, on
first call, so a missing primary API key surfaces as a fallback rather than
a crash at provider-selection time.
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from app.llm.base import LLMProvider, LLMResponse

logger = structlog.get_logger(__name__)


class FallbackLLMProvider(LLMProvider):
    def __init__(
        self,
        primary_factory: Callable[[], LLMProvider],
        fallback_factory: Callable[[], LLMProvider],
        primary_name: str,
        fallback_name: str,
    ) -> None:
        self._primary_factory = primary_factory
        self._fallback_factory = fallback_factory
        self._fallback_name = fallback_name
        self.provider_name = primary_name
        self.model = ""

    def _call(self, prompt: str, **kwargs: Any) -> LLMResponse:
        try:
            primary = self._primary_factory()
            response = primary._call(prompt, **kwargs)
            self.provider_name = primary.provider_name
            self.model = primary.model
            return response
        except Exception as exc:
            logger.warning(
                "llm_primary_failed_falling_back",
                primary=self.provider_name,
                fallback=self._fallback_name,
                error=str(exc)[:300],
            )
            fallback = self._fallback_factory()
            response = fallback._call(prompt, **kwargs)
            self.provider_name = fallback.provider_name
            self.model = fallback.model
            return response
