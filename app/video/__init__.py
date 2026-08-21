"""
Video composition module.

Re-exports VideoEditAgent helpers and exposes a clean VideoCompositor
class for use outside the agent pipeline (e.g. tests, one-off scripts).

Usage:
    from app.video.compositor import VideoCompositor
    comp = VideoCompositor()
    final = comp.compose(context)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class VideoCompositor:
    """
    Thin facade over VideoEditAgent for use outside the agent pipeline.

    For full pipeline use, prefer VideoEditAgent directly.
    """

    def compose(self, context: Any) -> Path:
        """
        Run the full video composition pipeline for the given AgentContext.
        Returns the path to final.mp4.
        """
        from app.agents.video_edit_agent import VideoEditAgent
        result = VideoEditAgent().run(context)
        if not result.success:
            raise RuntimeError(f"Video composition failed: {result.error}")
        return result.output

    def ken_burns(
        self,
        image_path: Path,
        audio_path: Path | None,
        output_path: Path,
        duration: float = 8.0,
        animation: str = "zoom-in",
    ) -> Path:
        """
        Create a single scene clip with Ken Burns motion from a still image.
        Useful for testing individual scenes.
        """
        from app.agents.video_edit_agent import _ken_burns_filter, _ffmpeg
        from app.config.settings import settings

        w, h, fps = settings.video_width, settings.video_height, settings.video_fps
        vf = _ken_burns_filter(animation, duration, w, h)

        if audio_path and audio_path.exists():
            _ffmpeg(
                "-loop", "1", "-i", str(image_path),
                "-i", str(audio_path),
                "-vf", vf,
                "-c:v", settings.video_codec,
                "-c:a", settings.audio_codec,
                "-t", str(duration),
                "-shortest",
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                str(output_path),
            )
        else:
            _ffmpeg(
                "-loop", "1", "-i", str(image_path),
                "-vf", vf,
                "-c:v", settings.video_codec,
                "-t", str(duration),
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-an",
                str(output_path),
            )
        return output_path
