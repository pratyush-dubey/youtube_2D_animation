"""
YouTube Data API v3 uploader.

Uploads a video as PRIVATE by default.
Optionally uploads a thumbnail.
Optionally publishes (changes privacy to public) after human review.

Quota note: YouTube Data API v3 free quota = 10,000 units/day.
  - video.insert = 1,600 units
  - thumbnails.set = 50 units
  - videos.update (publish) = 50 units
Total for one full upload+publish: ~1,700 units.
At free quota, this allows ~5 full uploads/day.
"""
from __future__ import annotations

import time
from datetime import UTC
from pathlib import Path
from typing import Any

import structlog

from app.config.settings import settings
from app.database.models import YouTubeUpload
from app.database.session import get_session
from app.seo.schemas import SEOMetadata

logger = structlog.get_logger(__name__)

_CHUNK_SIZE = 256 * 1024 * 10  # 2.5 MB resumable upload chunks


class UploadResult:
    def __init__(
        self,
        video_id: str,
        url: str,
        privacy_status: str,
        thumbnail_uploaded: bool = False,
    ) -> None:
        self.video_id = video_id
        self.url = url
        self.privacy_status = privacy_status
        self.thumbnail_uploaded = thumbnail_uploaded

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "url": self.url,
            "privacy_status": self.privacy_status,
            "thumbnail_uploaded": self.thumbnail_uploaded,
        }


class YouTubeUploader:
    """
    Uploads video + thumbnail to YouTube using the official Data API v3.

    Safety guarantees:
      - Default privacy is PRIVATE.
      - Will only publish publicly if settings.auto_publish is True.
      - Never uploads if youtube_client_id is empty.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def upload(
        self,
        video_path: Path,
        metadata: SEOMetadata,
        thumbnail_path: Path | None = None,
        privacy_status: str | None = None,
    ) -> UploadResult:
        """
        Upload video to YouTube.

        Args:
            video_path: Path to the final MP4.
            metadata: SEO metadata (title, description, tags).
            thumbnail_path: Optional path to 1280x720 JPEG thumbnail.
            privacy_status: Override privacy; defaults to settings.youtube_privacy_status.

        Returns:
            UploadResult with video_id and URL.
        """
        # Guard: credentials configured?
        if not settings.youtube_client_id or not settings.youtube_client_secret:
            raise ValueError(
                "YouTube credentials not configured. "
                "Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env"
            )

        # Guard: video file exists?
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Determine privacy status
        privacy = privacy_status or settings.youtube_privacy_status
        # NEVER default to public — always require explicit opt-in
        if privacy == "public" and not settings.auto_publish:
            logger.warning(
                "youtube_upload_privacy_downgraded",
                reason="auto_publish=false; uploading as private",
            )
            privacy = "private"

        logger.info(
            "youtube_upload_starting",
            project=self.project_id,
            video=str(video_path),
            privacy=privacy,
        )

        # Check for existing upload (resume support)
        existing = self._load_existing_upload()
        if existing:
            logger.info(
                "youtube_upload_already_exists",
                project=self.project_id,
                video_id=existing.video_id,
            )
            return UploadResult(
                video_id=existing.video_id,
                url=existing.url,
                privacy_status=existing.privacy_status,
                thumbnail_uploaded=existing.thumbnail_uploaded,
            )

        # Build API service
        youtube = self._build_service()

        # Upload video
        video_id = self._upload_video(youtube, video_path, metadata, privacy)
        url = f"https://www.youtube.com/watch?v={video_id}"

        logger.info(
            "youtube_upload_complete",
            project=self.project_id,
            video_id=video_id,
            url=url,
            privacy=privacy,
        )

        # Upload thumbnail
        thumb_uploaded = False
        if thumbnail_path and thumbnail_path.exists():
            try:
                self._upload_thumbnail(youtube, video_id, thumbnail_path)
                thumb_uploaded = True
                logger.info("youtube_thumbnail_uploaded", video_id=video_id)
            except Exception as exc:
                logger.warning(
                    "youtube_thumbnail_upload_failed",
                    video_id=video_id,
                    error=str(exc),
                )

        # Persist result
        result = UploadResult(
            video_id=video_id,
            url=url,
            privacy_status=privacy,
            thumbnail_uploaded=thumb_uploaded,
        )
        self._save_upload(result)
        return result

    def publish(self, video_id: str) -> None:
        """
        Change a private/unlisted video to public.
        Only callable when AUTO_PUBLISH=true OR called explicitly.
        """
        logger.info("youtube_publishing_video", video_id=video_id)
        youtube = self._build_service()
        youtube.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                },
            },
        ).execute()

        # Update DB record
        with get_session() as session:
            row = (
                session.query(YouTubeUpload)
                .filter_by(project_id=self.project_id)
                .first()
            )
            if row:
                from datetime import datetime
                row.privacy_status = "public"
                row.published_at = datetime.now(UTC)
                session.add(row)

        logger.info("youtube_video_published", video_id=video_id)

    def schedule(self, video_id: str, publish_at: str) -> None:
        """Schedule an already uploaded private video after human approval."""
        logger.info("youtube_scheduling_video", video_id=video_id, publish_at=publish_at)
        youtube = self._build_service()
        youtube.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": {
                    "privacyStatus": "private",
                    "publishAt": publish_at,
                    "selfDeclaredMadeForKids": False,
                },
            },
        ).execute()
        logger.info("youtube_video_scheduled", video_id=video_id, publish_at=publish_at)

    # ── private ────────────────────────────────────────────────────────────

    def _build_service(self):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ImportError(
                "google-api-python-client not installed. "
                "Run: pip install google-api-python-client"
            ) from exc

        from app.youtube.auth import get_credentials
        creds = get_credentials()
        return build("youtube", "v3", credentials=creds)

    def _upload_video(
        self,
        youtube,
        video_path: Path,
        metadata: SEOMetadata,
        privacy: str,
    ) -> str:
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise ImportError(
                "google-api-python-client not installed."
            ) from exc

        body = {
            "snippet": {
                "title": metadata.best_title[:100],
                "description": metadata.description[:5000],
                "tags": metadata.tags[:500],   # API limit
                "categoryId": settings.youtube_category_id,
                "defaultLanguage": metadata.default_language,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
                "madeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            chunksize=_CHUNK_SIZE,
            resumable=True,
        )

        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        attempt = 0
        while response is None:
            attempt += 1
            try:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    logger.info("youtube_upload_progress", pct=pct, project=self.project_id)
            except Exception as exc:
                if attempt >= settings.max_retries:
                    raise
                wait = settings.retry_backoff_base ** attempt
                logger.warning(
                    "youtube_upload_chunk_failed_retrying",
                    attempt=attempt,
                    wait=wait,
                    error=str(exc),
                )
                time.sleep(wait)

        return response["id"]

    def _upload_thumbnail(self, youtube, video_id: str, thumbnail_path: Path) -> None:
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise ImportError("google-api-python-client not installed.") from exc

        media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()

    def _load_existing_upload(self) -> YouTubeUpload | None:
        with get_session() as session:
            row = (
                session.query(YouTubeUpload)
                .filter_by(project_id=self.project_id)
                .first()
            )
            if row and row.video_id:
                # Detach safely
                from sqlalchemy.orm import make_transient
                session.expunge(row)
                make_transient(row)
                return row
        return None

    def _save_upload(self, result: UploadResult) -> None:
        from datetime import datetime
        with get_session() as session:
            row = (
                session.query(YouTubeUpload)
                .filter_by(project_id=self.project_id)
                .first()
            )
            if row is None:
                row = YouTubeUpload(project_id=self.project_id)
                session.add(row)
            row.video_id = result.video_id
            row.url = result.url
            row.privacy_status = result.privacy_status
            row.thumbnail_uploaded = result.thumbnail_uploaded
            row.uploaded_at = datetime.now(UTC)
