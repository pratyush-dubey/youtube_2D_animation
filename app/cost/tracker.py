"""
Cost tracker — records every external API call and estimates its USD cost.
Cost estimates are approximate; always check your provider's billing dashboard.
"""
from __future__ import annotations

from typing import Any

import structlog

from app.database.models import ApiCost
from app.database.session import get_session

logger = structlog.get_logger(__name__)

# Approximate prices per 1 000 tokens (input / output) in USD — updated 2025-01
# These are best-effort estimates; real billing may differ.
_PRICING: dict[str, dict[str, float]] = {
    "openai": {
        "gpt-4o": (0.005, 0.015),           # $5/$15 per 1M
        "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-3.5-turbo": (0.0005, 0.0015),
    },
    "gemini": {
        "gemini-1.5-flash": (0.000075, 0.0003),   # free tier up to quota
        "gemini-1.5-pro": (0.00125, 0.005),
    },
    "ollama": {},   # local — no cost
}


def _estimate_cost(provider: str, model: str, in_tokens: int, out_tokens: int) -> float:
    provider_prices = _PRICING.get(provider.lower(), {})
    # Sort by key length descending so "gpt-4o-mini" matches before "gpt-4o"
    for key, (in_price, out_price) in sorted(provider_prices.items(), key=lambda x: -len(x[0])):
        if key in model.lower():
            return round(
                (in_tokens / 1_000) * in_price + (out_tokens / 1_000) * out_price,
                6,
            )
    return 0.0


class CostTracker:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def record(
        self,
        provider: str,
        model: str,
        operation: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        cost = _estimate_cost(provider, model, input_tokens, output_tokens)
        with get_session() as session:
            session.add(
                ApiCost(
                    project_id=self.project_id,
                    provider=provider,
                    model=model,
                    operation=operation,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost_usd=cost,
                )
            )
        if provider != "ollama":
            logger.info(
                "api_cost",
                project=self.project_id,
                provider=provider,
                model=model,
                operation=operation,
                in_tokens=input_tokens,
                out_tokens=output_tokens,
                usd=cost,
            )
        return cost

    def total(self) -> float:
        with get_session() as session:
            rows = (
                session.query(ApiCost)
                .filter_by(project_id=self.project_id)
                .all()
            )
            return round(sum(r.estimated_cost_usd for r in rows), 6)
