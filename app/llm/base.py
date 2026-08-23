"""
Abstract base class for all LLM providers.
Every provider must implement generate() and generate_json().
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any

import structlog

from app.config.settings import settings

logger = structlog.get_logger(__name__)


class LLMResponse:
    """Normalised response from any LLM provider."""

    def __init__(
        self,
        content: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
        provider: str = "",
    ) -> None:
        self.content = content
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        self.provider = provider

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"LLMResponse(provider={self.provider!r}, model={self.model!r}, "
            f"in={self.input_tokens}, out={self.output_tokens})"
        )


class LLMProvider(ABC):
    """
    Abstract LLM provider.

    Subclasses implement _call() which does the actual network/process call.
    Retry logic, JSON extraction, and cost tracking live here in the base.
    """

    provider_name: str = "base"

    def generate(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """
        Generate text from a prompt with automatic retry + exponential backoff.
        kwargs override default generation parameters (temperature, max_tokens …).
        """
        max_retries = kwargs.pop("max_retries", settings.llm_max_retries)
        delay = settings.llm_retry_delay

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self._call(prompt, **kwargs)
                logger.debug(
                    "llm_call_success",
                    provider=self.provider_name,
                    attempt=attempt,
                    in_tokens=response.input_tokens,
                    out_tokens=response.output_tokens,
                )
                return response
            except Exception as exc:
                last_exc = exc
                # Extract retry-after hint from 429/503 messages if present
                wait = self._parse_retry_after(str(exc))
                logger.warning(
                    "llm_call_failed",
                    provider=self.provider_name,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(exc),
                )
                if attempt < max_retries:
                    sleep_time = wait if wait else (delay * (2 ** (attempt - 1)))
                    logger.info("llm_retrying", wait_s=round(sleep_time, 1), attempt=attempt)
                    time.sleep(sleep_time)

        detail = " ".join(str(last_exc).split())[:2000]
        raise RuntimeError(
            f"LLM provider {self.provider_name!r} failed after {max_retries} attempts: {detail}"
        ) from last_exc

    @staticmethod
    def _parse_retry_after(error_msg: str) -> float | None:
        """Extract a retry-after seconds value from 429/503 error messages."""
        import re
        # Gemini API format: "Please retry in 25.4s" or "retryDelay: '25s'"
        m = re.search(r"retry[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*s", error_msg, re.IGNORECASE)
        if m:
            return min(float(m.group(1)) + 2, 65)  # cap at 65s, add 2s buffer
        return None

    def generate_json(
        self, prompt: str, schema_hint: str = "", **kwargs: Any
    ) -> tuple[dict[str, Any], "LLMResponse"]:
        """
        Generate text and parse the result as JSON.
        Automatically extracts JSON from markdown code fences if necessary.
        Retries on parse failure up to llm_max_retries times.

        Returns:
            (parsed_dict, last_llm_response) — callers use the response for token/cost tracking.
        """
        # This is the total request budget. Do not multiply JSON-repair retries
        # by the provider's own retry loop.
        max_retries = kwargs.pop("max_retries", settings.llm_max_retries)
        last_raw = ""
        last_response: LLMResponse | None = None
        current_prompt = prompt
        for attempt in range(1, max_retries + 1):
            last_response = self.generate(
                current_prompt, max_retries=1, json_mode=True, **kwargs
            )
            last_raw = last_response.content.strip()
            parsed = _extract_json(last_raw)
            if parsed is not None:
                return parsed, last_response

            logger.warning(
                "json_parse_failed",
                provider=self.provider_name,
                attempt=attempt,
                max_retries=max_retries,
                snippet=last_raw[:200],
            )
            # Ask the model to fix its output on the next attempt
            current_prompt = (
                f"{prompt}\n\n"
                "IMPORTANT: Your previous response was not valid JSON. "
                "Return ONLY a valid JSON object with no markdown, no explanation.\n"
                + (f"Expected schema hint: {schema_hint}" if schema_hint else "")
            )

        raise ValueError(
            f"LLM provider {self.provider_name!r} did not return valid JSON "
            f"after {max_retries} attempts. Last raw output: {last_raw[:300]}"
        )

    @abstractmethod
    def _call(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """Provider-specific implementation. Must return LLMResponse."""
        ...


# ── JSON extraction helpers ────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any] | None:
    """
    Try multiple strategies to extract a JSON object from a model response.
    Returns the parsed dict, or None if all strategies fail.
    """
    # Strategy 1: direct parse — only accept dicts, not arrays or scalars
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip markdown code fence ```json … ``` or ``` … ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 3: find first { … } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None
