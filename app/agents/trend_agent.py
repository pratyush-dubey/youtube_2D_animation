"""
TrendAgent — finds trending topics in a niche using YouTube Data API
and Google Trends (via pytrends). Falls back to LLM-suggested topics
if external APIs fail.

No API key is required for Google Trends (pytrends scrapes the public
endpoint). YouTube Data API is used when configured.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.llm.factory import get_llm_provider

logger = structlog.get_logger(__name__)


class TrendAgent(Agent):
    name = "trend_agent"
    max_retries = 1

    def __init__(self, niche: str = "science and technology", llm=None) -> None:
        self.niche = niche
        self.llm = llm or get_llm_provider()

    def _execute(self, context: AgentContext) -> list[dict]:
        topics = []

        # Strategy 1 — pytrends (free, no key)
        topics = self._try_pytrends() or topics

        # Strategy 2 — YouTube trending search (needs YT API key)
        if not topics:
            topics = self._try_youtube_trending() or topics

        # Strategy 3 — LLM fallback
        if not topics:
            topics = self._llm_suggest_topics(context)

        # Score and sort
        topics = sorted(topics, key=lambda t: t.get("score", 0), reverse=True)
        context.trending_topics = topics

        logger.info(
            "trends_found",
            project=context.project_id,
            niche=self.niche,
            count=len(topics),
            top=topics[0]["topic"] if topics else "none",
        )
        return topics

    # ── strategies ──────────────────────────────────────────────────────────

    def _try_pytrends(self) -> list[dict]:
        try:
            from pytrends.request import TrendReq
            pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
            # Get related queries for the niche keyword
            pytrends.build_payload([self.niche], timeframe="now 7-d", geo="US")
            related = pytrends.related_queries()
            topics = []
            for kw, data in related.items():
                top_df = data.get("top")
                if top_df is not None and not top_df.empty:
                    for _, row in top_df.head(10).iterrows():
                        topics.append({
                            "topic": row["query"],
                            "score": int(row["value"]),
                            "source": "google_trends",
                        })
            return topics
        except Exception as exc:
            logger.warning("pytrends_failed", error=str(exc))
            return []

    def _try_youtube_trending(self) -> list[dict]:
        from app.config.settings import settings
        if not settings.youtube_client_id:
            return []
        try:
            from app.youtube.auth import get_credentials
            from googleapiclient.discovery import build
            creds = get_credentials()
            yt = build("youtube", "v3", credentials=creds)
            resp = yt.search().list(
                part="snippet",
                q=self.niche,
                type="video",
                order="viewCount",
                publishedAfter="2024-01-01T00:00:00Z",
                maxResults=10,
            ).execute()
            topics = []
            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                topics.append({
                    "topic": snippet.get("title", ""),
                    "score": 80,
                    "source": "youtube_trending",
                    "channel": snippet.get("channelTitle", ""),
                })
            return topics
        except Exception as exc:
            logger.warning("youtube_trending_failed", error=str(exc))
            return []

    def _llm_suggest_topics(self, context: AgentContext) -> list[dict]:
        prompt = (
            f"You are a YouTube content strategist. "
            f"Suggest 10 trending video topics in the niche: {self.niche}.\n"
            f"Return a JSON array of objects with keys: topic, reason, estimated_search_volume.\n"
            f"Base suggestions on topics that:\n"
            f"- Are currently popular or trending\n"
            f"- Have high search volume potential\n"
            f"- Are suitable for a {context.style} YouTube channel\n"
            f"- Can fill {context.target_duration_seconds // 60} minutes of content\n"
            f"Return ONLY valid JSON array."
        )
        try:
            raw, _ = self.llm.generate_json(prompt, schema_hint="trending_topics")
            items = raw if isinstance(raw, list) else raw.get("topics", raw.get("items", []))
            return [
                {
                    "topic": t.get("topic", str(t)),
                    "score": 50,
                    "source": "llm",
                    "reason": t.get("reason", ""),
                }
                for t in (items if isinstance(items, list) else [])
            ]
        except Exception as exc:
            logger.warning("llm_trend_suggest_failed", error=str(exc))
            return [{"topic": f"Fascinating facts about {self.niche}", "score": 40, "source": "fallback"}]
