"""
Ollama provider — talks to a locally running Ollama server.
https://ollama.ai  |  Local, free, MIT-licensed server.
"""
from __future__ import annotations

from typing import Any

import requests

from app.config.settings import settings
from app.llm.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout

    def _call(self, prompt: str, **kwargs: Any) -> LLMResponse:
        temperature = kwargs.get("temperature", settings.llm_temperature)
        max_tokens = kwargs.get("max_tokens", settings.llm_max_tokens)

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("response", "")
        # Ollama returns prompt_eval_count / eval_count for token usage
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self.model,
            provider=self.provider_name,
        )

    def is_available(self) -> bool:
        """Quick health check — returns True if the Ollama server is reachable."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
