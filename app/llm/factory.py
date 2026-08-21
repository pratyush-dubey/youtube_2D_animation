"""
LLM provider factory.
Returns a ready-to-use LLMProvider based on the configured LLM_PROVIDER env var.
"""
from __future__ import annotations

from app.config.settings import settings
from app.llm.base import LLMProvider


def get_llm_provider(override: str | None = None) -> LLMProvider:
    """
    Return the configured LLM provider instance.

    Args:
        override: Optional provider name to use instead of settings.llm_provider.
                  Useful in tests and CLI commands.

    Returns:
        A concrete LLMProvider subclass instance.

    Raises:
        ValueError: If the requested provider name is unknown.
    """
    provider_name = (override or settings.llm_provider).lower()

    if provider_name == "ollama":
        from app.llm.ollama_provider import OllamaProvider
        return OllamaProvider()

    if provider_name == "openai":
        from app.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()

    if provider_name == "gemini":
        from app.llm.gemini_provider import GeminiProvider
        return GeminiProvider()

    raise ValueError(
        f"Unknown LLM provider: {provider_name!r}. "
        "Valid options: ollama, openai, gemini"
    )
