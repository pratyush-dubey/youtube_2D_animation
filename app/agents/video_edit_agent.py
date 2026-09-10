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

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings

logger = structlog.get_logger(__name__)

W = settings.video_width
H = settings.video_height
FPS = settings.video_fps


def _video_dimensions(aspect_ratio: str) -> tuple[int, int]:
    """Return even output dimensions for long-form, Shorts, and square video."""
    ratio = str(aspect_ratio or "16:9").strip()
    if ratio == "9:16":
        return 1080, 1920
    if ratio == "1:1":
        return 1080, 1080
    return settings.video_width, settings.video_height


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

        self.render_width, self.render_height = _video_dimensions(context.aspect_ratio)

        output_dir = context.output_dir
        final_mp4 = output_dir / "final.mp4"
        render_manifest = output_dir / "render_manifest.json"
        render_key = _render_key(context)

        if (
            final_mp4.exists()
            and final_mp4.stat().st_size > 10_000
            and _manifest_matches(render_manifest, render_key)
        ):
            logger.info("video_already_exists", project=context.project_id)
            context.video_path = final_mp4
            return final_mp4

        # Build individual scene clips
        scene_clips: list[Path] = []
        rendered_scenes: list[dict] = []
        self.rendered_audio_cues: list[dict] = []
        for scene in context.storyboard:
            clip = self._build_scene_clip(scene, context)
            if clip and clip.exists():
                scene_clips.append(clip)
                rendered_scenes.append(scene)

        audio_dir = output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "audio_cues.json").write_text(
            json.dumps(self.rendered_audio_cues, indent=2), encoding="utf-8"
        )

        if not scene_clips:
            raise RuntimeError("No scene clips were generated")

        # Persist the exact editable/deterministic plan used by the renderer.
        # Asset regeneration can therefore leave voice, timing, and unrelated
        # scene components untouched.
        (output_dir / "production_plan.json").write_text(
            json.dumps(
                {
                    "production_version": 1,
                    "project_id": context.project_id,
                    "quality_threshold": settings.animation_quality_threshold,
                    "scenes": rendered_scenes,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Concatenate all scenes
        concat_mp4 = output_dir / "concat.mp4"
        overlaps = self._concat_clips(scene_clips, rendered_scenes, concat_mp4)

        # Generate phrase-level captions and separately styled scene titles.
        subtitle_path = output_dir / "subtitles.srt"
        clip_durations = [_probe_duration(p) for p in scene_clips]
        self._generate_srt(rendered_scenes, subtitle_path, clip_durations, overlaps)
        ass_path = output_dir / "captions.ass"
        self._generate_ass(
            rendered_scenes,
            ass_path,
            clip_durations,
            overlaps,
            include_captions=not _is_cinematic_documentary(context.style),
        )

        subtitled_mp4 = output_dir / "subtitled.mp4"
        if ass_path.exists():
            self._burn_subtitles(concat_mp4, ass_path, subtitled_mp4)
        else:
            shutil.copy2(concat_mp4, subtitled_mp4)

        # Mix background music
        if context.music_path and context.music_path.exists():
            self._mix_music(subtitled_mp4, context.music_path, final_mp4)
        else:
            shutil.copy2(subtitled_mp4, final_mp4)

        context.video_path = final_mp4
        render_manifest.write_text(
            json.dumps({"render_key": render_key, "version": 10}, indent=2),
            encoding="utf-8",
        )
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

        # The storyboard owns the requested pacing. Narration may extend a
        # scene, but a fast TTS voice must not collapse a planned production.
        duration = float(scene.get("duration_seconds", 8.0))
        if audio_path and audio_path.exists() and not context.master_timeline:
            try:
                duration = max(
                    duration,
                    _probe_duration(audio_path) + float(settings.scene_padding_seconds),
                    3.0,
                )
            except Exception:
                pass

        if settings.render_provider == "veo":
            sfx_path = self._create_sfx(context.output_dir, scene)
            return self._build_veo_scene_clip(
                scene, img_path, audio_path, sfx_path, out, duration, context.aspect_ratio
            )

        # Every scene is upgraded to an editable scene graph before rendering.
        # The frame renderer provides camera, parallax, articulated character,
        # atmosphere, and lighting motion; FFmpeg remains the final encoder.
        from app.video.animated_renderer import Cinematic2DRenderer
        from app.video.timeline import build_production_scene, score_animation_plan

        scene.update(build_production_scene({**scene, "duration_seconds": duration}))
        quality_report = score_animation_plan(scene)
        scene["animation_quality"] = quality_report
        if quality_report["score"] < int(settings.animation_quality_threshold):
            raise RuntimeError(
                f"Scene {scene_id} animation score {quality_report['score']} is below "
                f"the required {settings.animation_quality_threshold}"
            )

        sfx_path = self._create_sfx(context.output_dir, scene)
        renderer = Cinematic2DRenderer(
            getattr(self, "render_width", W), getattr(self, "render_height", H), FPS
        )
        try:
            return renderer.render_scene(
                scene,
                img_path if img_path and img_path.exists() else None,
                out,
                narration_path=audio_path,
                sfx_path=sfx_path,
                character_sheet=context.character_sheet,
                quality=str(scene.get("render_quality") or settings.render_quality),
            )
        except Exception as exc:
            # Local modes may retry their own procedural renderer. Veo branches
            # above and never enters this fallback.
            logger.warning("animated_asset_render_failed_retrying_procedural", scene=scene_id, error=str(exc)[-300:])
            scene["render_mode"] = "PROCEDURAL_ANIMATION"
            context.warnings.append(
                f"Scene {scene_id}: generated asset failed; used procedural animation ({exc})"
            )
            return renderer.render_scene(
                scene, None, out,
                narration_path=audio_path,
                sfx_path=sfx_path,
                character_sheet=context.character_sheet,
                quality=str(scene.get("render_quality") or settings.render_quality),
            )

    def _build_veo_scene_clip(
        self, scene: dict, image_path: Path | None, narration_path: Path | None,
        sfx_path: Path | None, output_path: Path, duration: float, aspect_ratio: str,
    ) -> Path:
        """Generate one physically animated shot and lock it to master audio."""
        if not image_path or not image_path.is_file():
            raise RuntimeError(f"Veo scene {scene['scene_id']} requires an approved first-frame image")
        if duration > 8.001:
            raise RuntimeError(
                f"Veo scene {scene['scene_id']} is {duration:.3f}s; split it into <=8s action beats"
            )
        requested = 4 if duration <= 4 else (6 if duration <= 6 else 8)
        prompt = _veo_motion_prompt(scene, duration)
        raw_path = output_path.with_name(f"{output_path.stem}.veo_raw.mp4")
        manifest_path = raw_path.with_suffix(".json")
        source_key = hashlib.sha256(
            image_path.read_bytes() + prompt.encode("utf-8")
            + f"{settings.veo_model}|{requested}|{settings.veo_resolution}".encode("utf-8")
        ).hexdigest()
        cached = False
        if raw_path.is_file() and manifest_path.is_file():
            try:
                cached = json.loads(manifest_path.read_text(encoding="utf-8")).get("source_key") == source_key
            except (OSError, ValueError):
                cached = False
        if not cached:
            from app.video.veo_provider import VeoVideoProvider
            provider = VeoVideoProvider(model=settings.veo_model)
            provider.generate_from_image(
                prompt, image_path, raw_path,
                duration_seconds=requested,
                aspect_ratio=str(aspect_ratio or "16:9"),
                resolution=settings.veo_resolution,
                generate_audio=settings.veo_generate_audio,
                negative_prompt=(
                    "static image, frozen pose, slideshow, Ken Burns, camera-only motion, "
                    "rigid character translation, foot sliding, floating feet, morphing face, "
                    "extra limbs, broken anatomy, teleporting, jump cut, text, watermark"
                ),
                seed=19850000 + int(scene["scene_id"]),
            )
            manifest_path.write_text(json.dumps({
                "source_key": source_key, "provider": "veo", "model": settings.veo_model,
                "generated_duration": requested, "target_duration": duration,
                "source_image": str(image_path.resolve()), "prompt": prompt,
            }, indent=2), encoding="utf-8")
        self._conform_generated_clip(raw_path, narration_path, sfx_path, output_path, duration)
        return output_path

    def _conform_generated_clip(
        self, raw_path: Path, narration_path: Path | None, sfx_path: Path | None,
        output_path: Path, duration: float,
    ) -> None:
        inputs = ["-i", str(raw_path)]
        if narration_path and narration_path.is_file():
            inputs += ["-i", str(narration_path)]
        else:
            inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        has_sfx = bool(sfx_path and sfx_path.is_file())
        if has_sfx:
            inputs += ["-i", str(sfx_path)]
        width, height = getattr(self, "render_width", W), getattr(self, "render_height", H)
        filters = [
            f"[0:v]trim=duration={duration:.6f},setpts=PTS-STARTPTS,fps=24,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}[v]",
            f"[1:a]apad,atrim=duration={duration:.6f}[narr]",
        ]
        audio_map = "[narr]"
        if has_sfx:
            filters += [
                f"[2:a]volume=.58,apad,atrim=duration={duration:.6f}[sfx]",
                "[narr][sfx]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            ]
            audio_map = "[aout]"
        _ffmpeg(
            *inputs, "-filter_complex", ";".join(filters), "-map", "[v]", "-map", audio_map,
            "-c:v", settings.video_codec, "-preset", settings.video_preset,
            "-crf", str(settings.video_crf), "-pix_fmt", "yuv420p",
            "-c:a", settings.audio_codec, "-t", f"{duration:.6f}", str(output_path),
        )
    # ── concat ─────────────────────────────────────────────────────────────

    def _concat_clips(
        self, clips: list[Path], scenes: list[dict], output: Path
    ) -> list[float]:
        """Join clips with actual visual and audio crossfades.

        Returns one overlap duration per boundary so caption timing can use the
        exact same timeline.  A plain concat remains as a compatibility fallback.
        """
        if len(clips) == 1:
            shutil.copy2(clips[0], output)
            return []

        exact_master_clock = all(
            scene.get("shots") and scene["shots"][0].get("master_start") is not None
            for scene in scenes
        )
        if exact_master_clock:
            list_file = output.parent / "concat_list.txt"
            list_file.write_text(
                "".join(f"file '{clip.resolve()}'\n" for clip in clips), encoding="utf-8"
            )
            _ffmpeg("-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output))
            return [0.0] * (len(clips) - 1)

        durations = [_probe_duration(p) for p in clips]
        overlaps = [min(0.45, durations[i] / 4, durations[i + 1] / 4)
                    for i in range(len(clips) - 1)]
        inputs: list[str] = []
        for clip in clips:
            inputs.extend(["-i", str(clip)])

        filters: list[str] = []
        current_v = "[0:v]"
        current_a = "[0:a]"
        elapsed = durations[0]
        for i in range(1, len(clips)):
            overlap = overlaps[i - 1]
            transition = _ffmpeg_transition(scenes[i - 1].get("transition", "cut"))
            offset = max(elapsed - overlap, 0)
            next_v = f"[v{i}]"
            next_a = f"[a{i}]"
            filters.append(
                f"{current_v}[{i}:v]xfade=transition={transition}:"
                f"duration={overlap:.3f}:offset={offset:.3f}{next_v}"
            )
            filters.append(
                f"{current_a}[{i}:a]acrossfade=d={overlap:.3f}:c1=tri:c2=tri{next_a}"
            )
            current_v, current_a = next_v, next_a
            elapsed += durations[i] - overlap

        try:
            _ffmpeg(
                *inputs,
                "-filter_complex", ";".join(filters),
                "-map", current_v, "-map", current_a,
                "-c:v", settings.video_codec,
                "-preset", settings.video_preset,
                "-crf", str(settings.video_crf),
                "-c:a", settings.audio_codec,
                "-pix_fmt", "yuv420p", str(output),
            )
            return overlaps
        except subprocess.CalledProcessError as exc:
            logger.warning("transition_render_failed_fallback", error=exc.stderr[-300:])

        list_file = output.parent / "concat_list.txt"
        lines = [f"file '{c.resolve()}'\n" for c in clips]
        list_file.write_text("".join(lines), encoding="utf-8")
        _ffmpeg(
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c:v", settings.video_codec,
            "-preset", settings.video_preset,
            "-crf", str(settings.video_crf),
            "-c:a", settings.audio_codec,
            "-pix_fmt", "yuv420p",
            str(output),
        )
        return [0.0] * (len(clips) - 1)

    # ── subtitles ──────────────────────────────────────────────────────────

    def _generate_srt(
        self,
        scenes: list[dict],
        output: Path,
        durations: list[float] | None = None,
        overlaps: list[float] | None = None,
    ) -> None:
        lines = []
        t = 0.0
        cue = 1
        durations = durations or [float(s.get("duration_seconds", 8.0)) for s in scenes]
        overlaps = overlaps or [0.0] * max(len(scenes) - 1, 0)
        for scene_index, scene in enumerate(scenes):
            text = scene.get("narration", "").strip()
            dur = durations[scene_index]
            chunks = _caption_chunks(text)
            word_total = max(sum(len(c.split()) for c in chunks), 1)
            local = 0.0
            for chunk in chunks:
                chunk_dur = dur * len(chunk.split()) / word_total
                lines.append(
                    f"{cue}\n{_srt_time(t + local)} --> {_srt_time(t + local + chunk_dur)}"
                    f"\n{chunk}\n"
                )
                cue += 1
                local += chunk_dur
            t += dur
            if scene_index < len(overlaps):
                t -= overlaps[scene_index]
        if lines:
            output.write_text("\n".join(lines), encoding="utf-8")

    def _generate_ass(
        self, scenes: list[dict], output: Path,
        durations: list[float], overlaps: list[float], include_captions: bool = True,
    ) -> None:
        events: list[str] = []
        t = 0.0
        for i, scene in enumerate(scenes):
            dur = durations[i]
            title = str(scene.get("text_overlay") or "").strip()
            if title:
                overlay_style = _ass_overlay_style(scene)
                title_duration = dur if overlay_style in {"Date", "Headline"} else min(2.8, dur)
                events.append(
                    f"Dialogue: 1,{_ass_time(t)},{_ass_time(t + title_duration)},"
                    f"{overlay_style},,0,0,0,,{_ass_escape(title)}"
                )
            chunks = _caption_chunks(scene.get("narration", "")) if include_captions else []
            word_total = max(sum(len(c.split()) for c in chunks), 1)
            local = 0.0
            for chunk in chunks:
                chunk_dur = dur * len(chunk.split()) / word_total
                start = t + local
                end = t + local + chunk_dur
                events.append(
                    f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
                    f"{_ass_escape(chunk)}"
                )
                local += chunk_dur
            t += dur
            if i < len(overlaps):
                t -= overlaps[i]

        play_width = getattr(self, "render_width", W)
        play_height = getattr(self, "render_height", H)
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_width}
PlayResY: {play_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial,52,&H00FFFFFF,&H000000FF,&HCC07121E,&H9A07121E,-1,0,0,0,100,100,0,0,3,2,0,2,150,150,70,1
Style: Title,Arial,64,&H0039E6FF,&H000000FF,&HCC07121E,&H9007121E,-1,0,0,0,100,100,0,0,3,2,0,7,90,90,72,1
Style: Date,Arial,92,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,105,100,7,0,1,1,2,5,100,100,70,1
Style: Location,Arial,54,&H0039E6FF,&H000000FF,&HCC07121E,&H9007121E,-1,0,0,0,100,100,2,0,3,2,0,1,85,85,82,1
Style: Headline,Arial,68,&H00FFFFFF,&H000000FF,&HCC07121E,&H9007121E,-1,0,0,0,100,100,1,0,3,2,0,2,130,130,88,1
Style: Evidence,Arial,46,&H00FFFFFF,&H000000FF,&HCC07121E,&H9007121E,-1,0,0,0,100,100,0,0,3,2,0,3,90,90,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        output.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")

    def _burn_subtitles(self, video: Path, subtitle_file: Path, output: Path) -> None:
        """Burn SRT or ASS subtitles into the video using FFmpeg.

        Falls back to a copy without subtitles on Windows if libass is
        unavailable or if the path contains characters that break the filter.
        """
        # FFmpeg subtitles filter needs forward-slash paths and escaped colons
        # on Windows: C:/path/to/file.srt  (backslashes and colons both fail)
        subtitle_str = str(subtitle_file.resolve()).replace("\\", "/").replace(":", "\\:")
        vf = f"subtitles='{subtitle_str}'"
        try:
            _ffmpeg(
                "-i", str(video), "-vf", vf,
                "-c:v", settings.video_codec,
                "-preset", settings.video_preset,
                "-crf", str(settings.video_crf),
                "-c:a", "copy", str(output),
            )
        except subprocess.CalledProcessError as exc:
            # libass not available or path issue — skip subtitle burn, copy video as-is
            logger.warning(
                "subtitle_burn_failed_fallback",
                error=exc.stderr[-200:] if exc.stderr else str(exc),
                hint="Subtitles skipped; video still valid without burned-in captions.",
            )
            shutil.copy2(str(video), str(output))

    # ── music ducking ──────────────────────────────────────────────────────

    def _mix_music(self, video: Path, music: Path, output: Path) -> None:
        """Mix background music under narration with ducking via FFmpeg."""
        narration_db = settings.narration_volume_db
        music_db = settings.music_duck_db
        # Keep the narration in front, duck the score quickly around speech, then
        # master the complete mix to a consistent YouTube-friendly loudness.
        filter_complex = (
            f"[0:a]volume={narration_db}dB,loudnorm=I=-15:TP=-1.5:LRA=7[narr];"
            f"[1:a]volume={music_db}dB,aloop=loop=-1:size=2e+09[music];"
            "[music][narr]sidechaincompress=threshold=0.025:ratio=8:attack=12:release=350[ducked];"
            "[narr][ducked]amix=inputs=2:duration=first:normalize=0[mix];"
            "[mix]loudnorm=I=-14:TP=-1.5:LRA=7,"
            "alimiter=limit=0.72:attack=5:release=50:level=disabled[aout]"
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

    def _create_sfx(self, output_dir: Path, scene: dict) -> Path | None:
        timed = [event for event in scene.get("sfx_events") or [] if str(event.get("source", "")).lower() in _SFX_FILTERS]
        if timed:
            from pydub import AudioSegment
            duration_ms = round(float(scene.get("duration_seconds", 1.0)) * 1000)
            combined = AudioSegment.silent(duration=duration_ms, frame_rate=48000)
            cache_dir = output_dir / "audio" / "sfx" / "library"
            cache_dir.mkdir(parents=True, exist_ok=True)
            for event in timed:
                cue = str(event["source"]).lower()
                source_path = cache_dir / f"{cue}.wav"
                if not source_path.is_file() or source_path.stat().st_size < 500:
                    _ffmpeg("-f", "lavfi", "-i", _SFX_FILTERS[cue], "-ar", "48000", str(source_path))
                local_ms = max(0, round(float(event["local_start"]) * 1000))
                effect_ms = max(100, round((float(event["end"]) - float(event["start"])) * 1000))
                effect = AudioSegment.from_file(source_path)[:effect_ms]
                combined = combined.overlay(effect, position=local_ms)
                self.rendered_audio_cues.append({
                    "event_id": event["event_id"], "source": cue,
                    "start": event["start"], "end": event["end"],
                })
            path = output_dir / "audio" / "sfx" / f"scene_{int(scene['scene_id']):03d}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            combined.export(path, format="wav", parameters=["-acodec", "pcm_s16le"])
            return path
        cues = scene.get("sfx") or []
        cue = next((str(c).lower() for c in cues if str(c).lower() in _SFX_FILTERS), None)
        if cue is None:
            return None
        path = output_dir / "audio" / "sfx" / f"{cue}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size < 500:
            _ffmpeg("-f", "lavfi", "-i", _SFX_FILTERS[cue], "-ar", "48000", str(path))
        return path

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

_SFX_FILTERS = {
    "whoosh": (
        "anoisesrc=color=pink:duration=0.8,highpass=f=450,lowpass=f=5200,"
        "afade=t=in:d=0.08,afade=t=out:st=0.3:d=0.5,volume=0.22"
    ),
    "wind": "anoisesrc=color=pink:duration=2.2,lowpass=f=900,volume=0.10",
    "chime": "sine=frequency=880:duration=1.1,afade=t=out:st=0.25:d=0.8,volume=0.18",
    "ambient-space": "sine=frequency=82:duration=2.2,afade=t=out:st=1.0:d=1.2,volume=0.08",
    "footsteps": (
        r"aevalsrc='if(lt(mod(t\,0.62)\,0.075)\,"
        r"0.72*sin(2*PI*(78+22*exp(-mod(t\,0.62)*18))*t)*exp(-mod(t\,0.62)*34)\,0)':"
        "s=48000:d=6.75,lowpass=f=430,volume=0.42"
    ),
    "door": "sine=frequency=210:duration=1.2,afade=t=in:d=0.10,afade=t=out:st=0.35:d=0.80,volume=0.30",
    "street_ambience": "anoisesrc=color=pink:duration=8,lowpass=f=1200,volume=0.05",
}


def _veo_motion_prompt(scene: dict, duration: float) -> str:
    """Translate a timed shot into physical-performance language for Veo."""
    shots = scene.get("shots") or [{}]
    beats = []
    for shot in shots:
        start = float(shot.get("start", 0.0))
        end = start + float(shot.get("duration", duration))
        action = str(shot.get("action") or scene.get("character_action") or "react")
        camera = shot.get("camera") or "static"
        camera_move = camera.get("move", "static") if isinstance(camera, dict) else camera
        beats.append(
            f"{start:.2f}-{min(end, duration):.2f}s: the character physically performs {action}; "
            f"camera {camera_move}"
        )
    environment = str(scene.get("environment") or scene.get("visual_description") or "the established environment")
    return (
        "Animate the supplied image as one continuous cinematic documentary shot at 24 fps. "
        "Preserve the exact person identity, face, clothing, art style, architecture, lighting, "
        "and spatial layout from the first frame. "
        + " ".join(beats)
        + f" The performance lasts {duration:.2f} seconds. Every action must be visibly executed "
          "with articulated shoulders, elbows, wrists, hips, knees, ankles, torso, head, balance, "
          "weight transfer, contact, follow-through, and natural acceleration/deceleration. Walking "
          "requires alternating legs and opposing arm swing, planted-foot contact, bent knees, and no "
          "foot skating. Reaching requires the hand to travel to and contact the real prop. "
        + f"Environment: {environment}. Add restrained independent environmental motion appropriate "
          "to the scene (people, vehicles, foliage, fabric, dust, reflections, shadows or practical "
          "effects) while maintaining continuity. Camera motion supports the action but is not the "
          "only movement. No cuts, no montage, no pose morph, no newly appearing objects."
    )


def _render_key(context: AgentContext) -> str:
    payload: dict[str, Any] = {
        "version": 10,
        "render_provider": settings.render_provider,
        "veo_model": settings.veo_model if settings.render_provider == "veo" else None,
        "veo_resolution": settings.veo_resolution if settings.render_provider == "veo" else None,
        "storyboard": context.storyboard,
        "master_timeline": context.master_timeline,
        "fps": FPS,
        "size": list(_video_dimensions(context.aspect_ratio)),
        "video_codec": settings.video_codec,
        "video_preset": settings.video_preset,
        "video_crf": settings.video_crf,
        "audio_codec": settings.audio_codec,
        "music": _file_signature(context.music_path),
        "images": {str(k): _file_signature(v) for k, v in context.images.items()},
        "narration": {str(k): _file_signature(v) for k, v in context.narration_files.items()},
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_signature(path: Path | None) -> list[int] | None:
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def _manifest_matches(path: Path, render_key: str) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("render_key") == render_key
    except Exception:
        return False


def _ffmpeg_transition(name: str) -> str:
    return {
        "cut": "fadefast",
        "fade": "fadeblack",
        "dissolve": "dissolve",
        "wipe-right": "wiperight",
        "zoom-through": "zoomin",
    }.get(str(name).lower(), "fade")


def _caption_chunks(text: str, max_words: int = 7) -> list[str]:
    """Create compact caption phrases rather than paragraph-sized subtitles."""
    words = re.sub(r"\s+", " ", str(text)).strip().split()
    chunks: list[str] = []
    while words:
        take = min(max_words, len(words))
        if len(words) > max_words:
            for i in range(max_words, 3, -1):
                if words[i - 1].endswith((",", ";", ":", ".", "?", "!")):
                    take = i
                    break
        chunks.append(" ".join(words[:take]))
        words = words[take:]
    return chunks


def _ass_escape(text: str) -> str:
    return str(text).replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _ass_time(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    whole = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:
        whole += 1
        cs = 0
    return f"{h}:{m:02d}:{whole:02d}.{cs:02d}"


def _is_cinematic_documentary(style: str) -> bool:
    lowered = str(style).lower()
    return "documentary" in lowered or "cinematic" in lowered


def _ass_overlay_style(scene: dict) -> str:
    requested = str(scene.get("overlay_style", "")).lower()
    asset_type = str(scene.get("asset_type", "")).lower()
    if requested in {"date", "year"} or asset_type == "date-card":
        return "Date"
    if requested in {"location", "place"} or asset_type in {"location-card", "animated-map"}:
        return "Location"
    if requested in {"headline", "chapter", "title"}:
        return "Headline"
    if asset_type in {"newspaper-document", "evidence-board"}:
        return "Evidence"
    return "Title"


def _visual_treatment_filter(
    animation: str, duration: float, w: int, h: int, asset_type: str
) -> str:
    """Apply a visual-system-specific documentary grade and physical texture."""
    motion = _ken_burns_filter(animation, duration, w, h)
    asset_type = str(asset_type).lower()
    if asset_type in {"archival-portrait", "archival-footage"}:
        grade = "hue=s=0,eq=contrast=1.14:brightness=-0.035,noise=alls=3:allf=t,vignette=PI/4"
    elif asset_type in {"newspaper-document", "evidence-board"}:
        grade = "eq=contrast=1.12:saturation=0.45:brightness=-0.015,noise=alls=2:allf=t,vignette=PI/5"
    elif asset_type in {"animated-map", "diagram"}:
        grade = "eq=contrast=1.12:saturation=1.18:gamma=0.96,unsharp=5:5:0.45"
    elif asset_type in {"date-card", "location-card"}:
        grade = "eq=contrast=1.18:saturation=0.72:brightness=-0.04,noise=alls=2:allf=t,vignette=PI/4"
    else:
        grade = (
            "eq=contrast=1.10:saturation=0.92:gamma=0.94,"
            "colorbalance=rs=-0.025:gs=0.018:bs=-0.018,"
            "noise=alls=2:allf=t,vignette=PI/5"
        )
    frame = "drawbox=x=0:y=0:w=iw:h=12:c=black:t=fill,drawbox=x=0:y=ih-12:w=iw:h=12:c=black:t=fill"
    return f"{motion},{grade},{frame}"


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
        y_expr = f"{dy}/2"
        return (
            f"scale={ow}:{oh},"
            f"crop={w}:{h}:x='{x_expr}':y='{y_expr}'"
        )

    elif animation == "pan-right":
        # Crop window slides right-to-left
        x_expr = f"({dx})-({dx})*n/{N}"
        y_expr = f"{dy}/2"
        return (
            f"scale={ow}:{oh},"
            f"crop={w}:{h}:x='{x_expr}':y='{y_expr}'"
        )

    elif animation == "pan-up":
        x_expr = f"{dx}/2"
        y_expr = f"({dy})*n/{N}"
        return (
            f"scale={ow}:{oh},"
            f"crop={w}:{h}:x='{x_expr}':y='{y_expr}'"
        )

    elif animation == "pan-down":
        x_expr = f"{dx}/2"
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
        cw_expr = f"({ow}-({dx}/2)*n/{N})"
        ch_expr = f"({oh}-({dy}/2)*n/{N})"
        x_expr  = f"({dx}/2)*n/{N}"
        y_expr  = f"({oh}-{ch_expr})/2"
        return (
            f"scale={ow}:{oh},"
            f"crop=w='{cw_expr}':h='{ch_expr}':x='{x_expr}':y='{y_expr}',"
            f"scale={w}:{h}"
        )

    else:
        # "static" or unknown — still apply a very gentle zoom-in so the
        # video never looks completely frozen
        cw_expr = f"({ow}-({dx}/4)*n/{N})"
        ch_expr = f"({oh}-({dy}/4)*n/{N})"
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
