"""
ResearchAgent — gathers factual information about a topic using:
  1. Wikipedia API (free, no key)
  2. DuckDuckGo Instant Answer API (free, no key)
  3. Tavily Search API (generous free tier, best quality) — optional
  4. LLM knowledge fallback

All sources respect robots.txt / terms of service.
No scraping of arbitrary websites.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.llm.factory import get_llm_provider
from app.research.researcher import Researcher

logger = structlog.get_logger(__name__)


class ResearchAgent(Agent):
    name = "research_agent"
    max_retries = 2

    def __init__(self, llm=None) -> None:
        self.llm = llm or get_llm_provider()

    def _execute(self, context: AgentContext) -> Any:
        topic = context.chosen_topic or context.topic

        # ── Content safety pre-check ──────────────────────────────────────
        if settings.content_safety_enabled:
            self._check_topic_safety(topic)

        # Enrich LLM research with real web facts
        web_facts = self._gather_web_facts(topic)

        # Run core researcher (LLM-based with web context injected)
        researcher = Researcher(
            project_id=context.project_id,
            llm=self.llm,
            extra_context=web_facts,
        )
        result = researcher.run(topic=topic, language=context.language)
        context.research = result
        # The production director hydrates completed stages from the project
        # directory on resume.  Researcher also persists to SQL, but that is a
        # separate cache and cannot satisfy the director's file contract.
        research_path = context.output_dir / "research.json"
        research_path.parent.mkdir(parents=True, exist_ok=True)
        research_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        logger.info(
            "research_complete",
            project=context.project_id,
            topic=topic,
            facts=len(result.facts),
            sources=len(web_facts),
        )
        return result

    # ── web data gathering ────────────────────────────────────────────────

    def _gather_web_facts(self, topic: str) -> list[dict]:
        facts = []

        wiki = self._wikipedia_search(topic)
        if wiki:
            facts.append({"source": "wikipedia", "content": wiki[:3000]})

        ddg = self._duckduckgo_instant(topic)
        if ddg:
            facts.append({"source": "duckduckgo", "content": ddg[:1000]})

        tavily = self._tavily_search(topic)
        facts.extend(tavily)

        return facts

    def _wikipedia_search(self, topic: str) -> str:
        try:
            import urllib.request, urllib.parse
            query = urllib.parse.quote(topic)
            url = (
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}"
                "?redirect=true"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "AIYouTubeBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return data.get("extract", "")
        except Exception as exc:
            logger.debug("wikipedia_failed", error=str(exc))
            return ""

    def _duckduckgo_instant(self, topic: str) -> str:
        try:
            import urllib.request, urllib.parse
            query = urllib.parse.quote(topic)
            url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "AIYouTubeBot/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return data.get("AbstractText", "") or data.get("Answer", "")
        except Exception as exc:
            logger.debug("duckduckgo_failed", error=str(exc))
            return ""

    def _tavily_search(self, topic: str) -> list[dict]:
        api_key = getattr(settings, "tavily_api_key", "")
        if not api_key:
            return []
        try:
            import urllib.request, json as _json
            payload = _json.dumps({
                "api_key": api_key,
                "query": topic,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
            }).encode()
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())
            results = []
            if data.get("answer"):
                results.append({"source": "tavily_answer", "content": data["answer"]})
            for r in data.get("results", [])[:3]:
                results.append({
                    "source": r.get("url", "tavily"),
                    "content": r.get("content", "")[:500],
                })
            return results
        except Exception as exc:
            logger.debug("tavily_failed", error=str(exc))
            return []

    # ── content safety ────────────────────────────────────────────────────

    # Patterns that are always rejected regardless of context
    _BLOCKED_PATTERNS = [
        "how to make a bomb", "how to make explosives", "how to make drugs",
        "child abuse", "csam", "how to hack", "ddos attack",
        "suicide method", "self harm method",
    ]

    def _check_topic_safety(self, topic: str) -> None:
        """
        Basic content safety gate.  Raises ValueError for clearly dangerous topics.
        This is a lightweight heuristic check — not a replacement for a proper
        content moderation API.
        """
        topic_lower = topic.lower()
        for pattern in self._BLOCKED_PATTERNS:
            if pattern in topic_lower:
                raise ValueError(
                    f"Content safety check failed: topic contains blocked pattern "
                    f"{pattern!r}. The system will not generate content on this topic."
                )
        logger.debug("content_safety_passed", topic=topic[:80])
