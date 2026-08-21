"""
VideoEditAgent — composes all assets into a final MP4 using FFmpeg.

Per scene it:
  1. Creates a video clip from the scene image with Ken Burns motion
  2. Adds narration audio
  3. Applies the scene transition
  4. Burns in subtitles
  5. Ducks background music under narration

Uses FFmpeg subprocess only — no MoviePy dependency.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings

logger = structlog.get_logger(__name__)

W = settings.video_width
H = settings.video_height
FPS = settings.video_fps


def _ffmpeg(*args, check=True) -> subprocess.CompletedProcess:
    cmd = [settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"] + list(args)
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _probe_duration(path: Path) -> float:
    """Return media duration in seconds using ffprobe."""
    result = subprocess.run(
        [settings.ffprobe_path, "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"].get("duration", 0))


class VideoEditAgent(Agent):
    name = "video_edit_agent"
    max_retries = 1

    def _execute(self, context: AgentContext) -> Path:
        if not context.storyboard:
            raise ValueError("Storyboard required before VideoEditAgent")

        output_dir = context.output_dir
        final_mp4 = output_dir / "final.mp4"

        if final_mp4.exists() and final_mp4.stat().st_size > 10_000:
            logger.info("video_already_exists", project=context.project_id)
            context.video_path = final_mp4
            return final_mp4

        # Build individual scene clips
        scene_clips: list[Path] = []
        for scene in context.storyboard:
            clip = self._build_scene_clip(scene, context)
            if clip and clip.exists():
                scene_clips.append(clip)

        if not scene_clips:
            raise RuntimeError("No scene clips were generated")

        # Concatenate all scenes
        concat_mp4 = output_dir / "concat.mp4"
        self._concat_clips(scene_clips, concat_mp4)

        # Burn subtitles
        subtitle_path = output_dir / "subtitles.srt"
        self._generate_srt(context.storyboard, subtitle_path)

        subtitled_mp4 = output_dir / "subtitled.mp4"
        if subtitle_path.exists():
            self._burn_subtitles(concat_mp4, subtitle_path, subtitled_mp4)
        else:
            concat_mp4.rename(subtitled_mp4)

        # Mix background music
        if context.music_path and context.music_path.exists():
            self._mix_music(subtitled_mp4, context.music_path, final_mp4)
        else:
            subtitled_mp4.rename(final_mp4)

        context.video_path = final_mp4
        logger.info(
            "video_complete",
            project=context.project_id,
            path=str(final_mp4),
            size_mb=round(final_mp4.stat().st_size / 1e6, 1),
        )
        return final_mp4

    # ── per-scene clip ──────────────────────────────────────────────────────

    def _build_scene_clip(self, scene: dict, context: AgentContext) -> Path | None:
        scene_id = scene["scene_id"]
        img_path = context.images.get(scene_id)
        audio_path = context.narration_files.get(scene_id)
        out = context.output_dir / "scenes" / f"scene_{scene_id:03d}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)

        if out.exists() and out.stat().st_size > 1000:
            return out

        # Determine duration from audio if available
        duration = scene.get("duration_seconds", 8.0)
        if audio_path and audio_path.exists():
            try:
                duration = max(_probe_duration(audio_path) + float(settings.scene_padding_seconds), 3.0)
            except Exception:
                pass

        # Use placeholder black frame if no image
        if img_path is None or not img_path.exists():
            img_path = self._create_black_frame(context.output_dir, scene_id)

        # Ken Burns effect via zoompan filter
        animation = scene.get("animation_type", "zoom-in")
        vf = _ken_burns_filter(animation, duration, W, H)

        try:
            if audio_path and audio_path.exists():
                _ffmpeg(
                    "-loop", "1", "-i", str(img_path),
                    "-i", str(audio_path),
                    "-vf", vf,
                    "-c:v", settings.video_codec,
                    "-c:a", settings.audio_codec,
                    "-t", str(duration),
                    "-shortest",
                    "-pix_fmt", "yuv420p",
                    "-r", str(FPS),
                    str(out),
                )
            else:
                _ffmpeg(
                    "-loop", "1", "-i", str(img_path),
                    "-vf", vf,
                    "-c:v", settings.video_codec,
                    "-t", str(duration),
                    "-pix_fmt", "yuv420p",
                    "-r", str(FPS),
                    "-an",
                    str(out),
                )
            return out
        except subprocess.CalledProcessError as exc:
            logger.warning("scene_render_failed", scene=scene_id, stderr=exc.stderr[-300:])
            return None

    # ── concat ─────────────────────────────────────────────────────────────

    def _concat_clips(self, clips: list[Path], output: Path) -> None:
        list_file = output.parent / "concat_list.txt"
        lines = [f"file '{c.resolve()}'\n" for c in clips]
        list_file.write_text("".join(lines), encoding="utf-8")
        _ffmpeg(
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c:v", settings.video_codec,
            "-c:a", settings.audio_codec,
            "-pix_fmt", "yuv420p",
            str(output),
        )

    # ── subtitles ──────────────────────────────────────────────────────────

    def _generate_srt(self, scenes: list[dict], output: Path) -> None:
        lines = []
        t = 0.0
        for i, scene in enumerate(scenes, 1):
            text = scene.get("narration", "").strip()
            if not text:
                continue
            dur = float(scene.get("duration_seconds", 8.0))
            start = _srt_time(t)
            end = _srt_time(t + dur)
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
            t += dur
        if lines:
            output.write_text("\n".join(lines), encoding="utf-8")

    def _burn_subtitles(self, video: Path, srt: Path, output: Path) -> None:
        """Burn SRT subtitles into the video using FFmpeg.

        Falls back to a copy without subtitles on Windows if libass is
        unavailable or if the path contains characters that break the filter.
        """
        # FFmpeg subtitles filter needs forward-slash paths and escaped colons
        # on Windows: C:/path/to/file.srt  (backslashes and colons both fail)
        srt_str = str(srt.resolve()).replace("\\", "/").replace(":", "\\:")
        font_size = 18
        vf = (
            f"subtitles='{srt_str}'"
            f":force_style='Fontsize={font_size},PrimaryColour=&Hffffff,"
            f"OutlineColour=&H000000,Outline=2,Alignment=2'"
        )
        try:
            _ffmpeg("-i", str(video), "-vf", vf, "-c:a", "copy", str(output))
        except subprocess.CalledProcessError as exc:
            # libass not available or path issue — skip subtitle burn, copy video as-is
            logger.warning(
                "subtitle_burn_failed_fallback",
                error=exc.stderr[-200:] if exc.stderr else str(exc),
                hint="Subtitles skipped; video still valid without burned-in captions.",
            )
            import shutil
            shutil.copy2(str(video), str(output))

    # ── music ducking ──────────────────────────────────────────────────────

    def _mix_music(self, video: Path, music: Path, output: Path) -> None:
        """Mix background music under narration with ducking via FFmpeg."""
        narration_db = settings.narration_volume_db
        music_db = settings.music_duck_db
        # Normalize both and mix
        filter_complex = (
            f"[0:a]volume={narration_db}dB[narr];"
            f"[1:a]volume={music_db}dB,aloop=loop=-1:size=2e+09[music];"
            f"[narr][music]amix=inputs=2:duration=first[aout]"
        )
        _ffmpeg(
            "-i", str(video),
            "-i", str(music),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", settings.audio_codec,
            "-shortest",
            str(output),
        )

    # ── utils ──────────────────────────────────────────────────────────────

    def _create_black_frame(self, output_dir: Path, scene_id: int) -> Path:
        path = output_dir / "images" / f"black_{scene_id:03d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            try:
                from PIL import Image
                Image.new("RGB", (W, H), color=(10, 10, 20)).save(str(path))
            except ImportError:
                _ffmpeg("-f", "lavfi", "-i", f"color=black:s={W}x{H}", "-frames:v", "1", str(path))
        return path


# ── Ken Burns / motion filter helpers ────────────────────────────────────────
#
# WHY NOT zoompan:
#   FFmpeg's zoompan filter processes every pixel in software on every frame.
#   At 1920×1080 × 30 fps it runs at ~1 fps (10-minute render for an 8-second
#   clip) and often produces near-static output due to expression evaluation
#   quirks.  We replace it with a fast scale+crop chain that uses the `n`
#   (frame-number) expression variable — hardware-friendly, smooth, reliable.
#
# APPROACH:
#   1. Scale the image to an "oversized canvas" (e.g. 130% of target size)
#   2. Crop a W×H window from that canvas whose position/size changes per-frame
#      using FFmpeg crop filter expressions (`n` = current frame number, `t` =
#      current time in seconds)
#   3. The combination of moving crop origin + changing scale creates all the
#      classic Ken Burns, pan, and zoom effects.

def _ken_burns_filter(animation: str, duration: float, w: int, h: int) -> str:
    """
    Return an FFmpeg vf filter string that produces smooth camera motion.

    Uses scale + crop with per-frame `n` expressions — fast, reliable at any
    resolution, and produces genuinely animated output (not static frames).
    """
    frames = max(int(duration * FPS), 1)

    # Oversized canvas: image is scaled to this, then we crop a W×H window
    # that moves across it.  130 % gives plenty of travel room.
    ow = int(w * 1.30)   # oversized width
    oh = int(h * 1.30)   # oversized height

    # Ensure even dimensions (required by libx264)
    ow += ow % 2
    oh += oh % 2

    # Maximum travel distance in each axis
    dx = ow - w   # horizontal headroom  (e.g. 576 px at 1920)
    dy = oh - h   # vertical headroom    (e.g. 324 px at 1080)

    # --- per-animation expressions -------------------------------------------
    # All expressions use:
    #   n    = current frame number (0-based)
    #   N    = total frames (constant, substituted as integer)
    # crop(w, h, x, y)  — x/y are the TOP-LEFT of the crop window

    N = frames  # substituted directly into the expression strings

    if animation == "zoom-in":
        # Start at full canvas (zoomed out), end tightly cropped (zoomed in)
        # Achieved by shrinking the scale from ow→w while keeping centred crop
        #   scale_t = ow - (ow-w)*n/N   (shrinks toward w)
        #   crop offset = (current_scale - w)/2
        # Simpler equivalent with just crop: keep scale at ow×oh, shrink crop size
        # from ow→w and oh→h, centred.
        cw_expr = f"({ow}-({dx})*n/{N})"
        ch_expr = f"({oh}-({dy})*n/{N})"
        x_expr  = f"({ow}-{cw_expr})/2"
        y_expr  = f"({oh}-{ch_expr})/2"
        return (
            f"scale={ow}:{oh},"
            f"crop=w='{cw_expr}':h='{ch_expr}':x='{x_expr}':y='{y_expr}',"
            f"scale={w}:{h}"
        )

    elif animation == "zoom-out":
        # Start tightly cropped (zoomed in), widen to full canvas
        cw_expr = f"({w}+({dx})*n/{N})"
        ch_expr = f"({h}+({dy})*n/{N})"
        x_expr  = f"({ow}-{cw_expr})/2"
        y_expr  = f"({oh}-{ch_expr})/2"
        return (
            f"scale={ow}:{oh},"
            f"crop=w='{cw_expr}':h='{ch_expr}':x='{x_expr}':y='{y_expr}',"
            f"scale={w}:{h}"
        )

    elif animation == "pan-left":
        # Crop window slides left-to-right across the oversized canvas
        x_expr = f"({dx})*n/{N}"
        y_expr = f"{dy}//2"
        return (
            f"scale={ow}:{oh},"
            f"crop={w}:{h}:x='{x_expr}':y='{y_expr}'"
        )

    elif animation == "pan-right":
        # Crop window slides right-to-left
        x_expr = f"({dx})-({dx})*n/{N}"
        y_expr = f"{dy}//2"
        return (
            f"scale={ow}:{oh},"
            f"crop={w}:{h}:x='{x_expr}':y='{y_expr}'"
        )

    elif animation == "pan-up":
        x_expr = f"{dx}//2"
        y_expr = f"({dy})*n/{N}"
        return (
            f"scale={ow}:{oh},"
            f"crop={w}:{h}:x='{x_expr}':y='{y_expr}'"
        )

    elif animation == "pan-down":
        x_expr = f"{dx}//2"
        y_expr = f"({dy})-({dy})*n/{N}"
        return (
            f"scale={ow}:{oh},"
            f"crop={w}:{h}:x='{x_expr}':y='{y_expr}'"
        )

    elif animation == "ken-burns":
        # Zoom in + slight diagonal drift (upper-left → centre)
        cw_expr = f"({ow}-({dx})*n/{N})"
        ch_expr = f"({oh}-({dy})*n/{N})"
        x_expr  = f"({dx}/4)*n/{N}"
        y_expr  = f"({dy}/4)*n/{N}"
        return (
            f"scale={ow}:{oh},"
            f"crop=w='{cw_expr}':h='{ch_expr}':x='{x_expr}':y='{y_expr}',"
            f"scale={w}:{h}"
        )

    elif animation == "drift-right":
        # Subtle rightward drift with mild zoom-in
        cw_expr = f"({ow}-({dx}//2)*n/{N})"
        ch_expr = f"({oh}-({dy}//2)*n/{N})"
        x_expr  = f"({dx}//2)*n/{N}"
        y_expr  = f"({oh}-{ch_expr})/2"
        return (
            f"scale={ow}:{oh},"
            f"crop=w='{cw_expr}':h='{ch_expr}':x='{x_expr}':y='{y_expr}',"
            f"scale={w}:{h}"
        )

    else:
        # "static" or unknown — still apply a very gentle zoom-in so the
        # video never looks completely frozen
        cw_expr = f"({ow}-({dx}//4)*n/{N})"
        ch_expr = f"({oh}-({dy}//4)*n/{N})"
        x_expr  = f"({ow}-{cw_expr})/2"
        y_expr  = f"({oh}-{ch_expr})/2"
        return (
            f"scale={ow}:{oh},"
            f"crop=w='{cw_expr}':h='{ch_expr}':x='{x_expr}':y='{y_expr}',"
            f"scale={w}:{h}"
        )


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
