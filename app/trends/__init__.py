"""
Trend analysis module.

Wraps TrendAgent to provide a clean standalone interface for finding
trending topics in a niche without running the full agent pipeline.

Usage:
    from app.trends.analyzer import TrendAnalyzer
    analyzer = TrendAnalyzer(niche="science and technology")
    topics = analyzer.get_trending(n=5)
"""
from __future__ import annotations

from typing import Any


class TrendAnalyzer:
    """
    Standalone trend analysis wrapper around TrendAgent.

    Useful for scheduled jobs, CLI commands, and testing trend detection
    independently of the full pipeline.
    """

    def __init__(
        self,
        niche: str = "science and technology",
        llm=None,
    ) -> None:
        self.niche = niche
        self._llm = llm

    def get_trending(self, n: int = 10) -> list[dict]:
        """
        Return up to n trending topics for the configured niche.

        Each result dict has:
          topic  — the topic string
          score  — relevance/trend score (higher = better)
          source — where the topic came from (google_trends | youtube | llm | fallback)
          reason — optional explanation (from LLM suggestions)
        """
        from app.agents.trend_agent import TrendAgent
        from app.agents.base import AgentContext
        from app.config.settings import settings

        # Minimal context — TrendAgent only needs project_id + style
        context = AgentContext(
            project_id="trend_analysis",
            topic=self.niche,
            style="documentary",
        )
        llm = self._llm or _get_llm()
        agent = TrendAgent(niche=self.niche, llm=llm)
        result = agent.run(context)

        topics = context.trending_topics or []
        return sorted(topics, key=lambda t: t.get("score", 0), reverse=True)[:n]

    def best_topic(self) -> str | None:
        """Return the single best trending topic string, or None."""
        topics = self.get_trending(n=1)
        return topics[0]["topic"] if topics else None


def _get_llm():
    from app.llm.factory import get_llm_provider
    return get_llm_provider()
