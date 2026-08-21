"""
YouTubeAgent — wrapper agent around the YouTube uploader.
Always uploads as PRIVATE first.
"""
from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings

logger = structlog.get_logger(__name__)


class YouTubeAgent(Agent):
    name = "youtube_agent"
    max_retries = 2

    def _execute(self, context: AgentContext) -> dict:
        if not context.video_path or not context.video_path.exists():
            raise ValueError("Video file required for YouTubeAgent")
        if context.seo is None:
            raise ValueError("SEOAgent must run before YouTubeAgent")

        from app.youtube.uploader import YouTubeUploader
        uploader = YouTubeUploader(project_id=context.project_id)
        result = uploader.upload(
            video_path=context.video_path,
            metadata=context.seo,
            thumbnail_path=context.thumbnail_path,
            privacy_status=settings.youtube_privacy_status,
        )

        context.youtube_video_id = result.video_id
        context.youtube_url = result.url

        logger.info(
            "youtube_upload_complete",
            project=context.project_id,
            video_id=result.video_id,
            url=result.url,
            privacy=result.privacy_status,
        )
        return result.to_dict()
