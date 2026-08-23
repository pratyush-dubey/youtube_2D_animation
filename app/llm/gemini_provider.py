"""
Google Gemini provider.

Uses the current `google-genai` SDK (google-genai >= 1.0).
Falls back to the deprecated `google-generativeai` SDK if the new one
is not installed (shows a one-time warning).

Free tier (as of 2025):
  gemini-1.5-flash  — 15 RPM, 1 500 RPD, 1M tokens/day
  gemini-2.0-flash  — 15 RPM, 1 500 RPD, 1M tokens/day
Commercial use: permitted under Google AI Studio terms.

Install:
    pip install google-genai          # recommended (new SDK)
    # or
    pip install google-generativeai   # deprecated but still works
"""
from __future__ import annotations

import warnings
from typing import Any

from app.config.settings import settings
from app.llm.base import LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model

        if not self.api_key:
            raise ValueError(
                "Gemini API key not set.\n"
                "Set GEMINI_API_KEY in your .env file.\n"
                "Get a free key at https://aistudio.google.com/apikey"
            )

        # Determine which SDK is available at construction time
        self._sdk = self._detect_sdk()

    # ── SDK detection ──────────────────────────────────────────────────────

    def _detect_sdk(self) -> str:
        """Return 'new' (google-genai) or 'legacy' (google-generativeai)."""
        try:
            import google.genai  # noqa: F401
            return "new"
        except ImportError:
            pass
        try:
            import google.generativeai  # noqa: F401
            warnings.warn(
                "google-generativeai is deprecated. "
                "Upgrade: pip install google-genai",
                FutureWarning,
                stacklevel=3,
            )
            return "legacy"
        except ImportError:
            raise ImportError(
                "No Gemini SDK found.\n"
                "Run: pip install google-genai\n"
                "or:  pip install google-generativeai"
            )

    # ── Core call ──────────────────────────────────────────────────────────

    def _call(self, prompt: str, **kwargs: Any) -> LLMResponse:
        if self._sdk == "new":
            return self._call_new_sdk(prompt, **kwargs)
        return self._call_legacy_sdk(prompt, **kwargs)

    def _call_new_sdk(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """google-genai >= 1.0 (current recommended SDK)."""
        from google import genai
        from google.genai import types

        temperature = kwargs.get("temperature", settings.llm_temperature)
        max_tokens = kwargs.get("max_tokens", settings.llm_max_tokens)

        # Disable automatic function calling (AFC) to suppress SDK warnings
        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                api_version="v1beta",
                timeout=settings.llm_request_timeout_seconds * 1000,
            ),
        )

        # The new SDK requires the "models/" prefix; add it if missing
        model_name = self.model
        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )

        content = response.text or ""

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self.model,
            provider=self.provider_name,
        )

    def _call_legacy_sdk(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """google-generativeai (deprecated, kept for compatibility)."""
        import google.generativeai as genai

        temperature = kwargs.get("temperature", settings.llm_temperature)
        max_tokens = kwargs.get("max_tokens", settings.llm_max_tokens)

        genai.configure(api_key=self.api_key)
        model_obj = genai.GenerativeModel(self.model)

        response = model_obj.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        content = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self.model,
            provider=self.provider_name,
        )
