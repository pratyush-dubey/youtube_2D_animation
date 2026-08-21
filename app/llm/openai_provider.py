"""
OpenAI provider — works with OpenAI's API and any OpenAI-compatible endpoint
(e.g. local llama.cpp servers, LM Studio, Together AI, etc.).
"""
from __future__ import annotations

from typing import Any

from app.config.settings import settings
from app.llm.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.base_url = base_url or settings.openai_base_url

        if not self.api_key:
            raise ValueError(
                "OpenAI API key not set. "
                "Set OPENAI_API_KEY in your .env file."
            )

    def _call(self, prompt: str, **kwargs: Any) -> LLMResponse:
        # Lazy import — only pay the cost if this provider is actually used
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package not installed. Run: pip install openai"
            ) from exc

        temperature = kwargs.get("temperature", settings.llm_temperature)
        max_tokens = kwargs.get("max_tokens", settings.llm_max_tokens)

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        completion = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = completion.choices[0].message.content or ""
        usage = completion.usage

        return LLMResponse(
            content=content,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=self.model,
            provider=self.provider_name,
        )
