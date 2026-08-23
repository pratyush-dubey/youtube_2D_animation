"""Deterministic frame renderer for cinematic 2D/2.5D scenes.

Pillow renders the editable scene graph frame-by-frame. FFmpeg remains the
encoder and audio compositor. The renderer deliberately has no static-image
success path: if an asset cannot be animated it switches to procedural depth,
camera, atmosphere, and vector-puppet motion and records that degradation.
"""
from __future__ import annotations

import hashlib
import math
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from app.config.settings import settings
from app.characters.errors import CharacterGenerationError, DIFFUSION_FAILURE
from app.video.blocking import character_blocking

QUALITY_PROFILES = {
    "DRAFT": (640, 360, 15),
    "PREVIEW": (960, 540, 24),
    "FINAL": (1280, 720, 30),
}


class Cinematic2DRenderer:
    """Render a production scene to an animated MP4."""

    def __init__(self, output_width: int, output_height: int, fps: int = 30) -> None:
        self.output_width = output_width
        self.output_height = output_height
        self.output_fps = fps

    def render_scene(
        self,
        scene: dict,
        background_path: Path | None,
        output_path: Path,
        narration_path: Path | None = None,
        sfx_path: Path | None = None,
        character_sheet: dict | None = None,
        quality: str = "FINAL",
    ) -> Path:
        duration = max(1.0, float(scene.get("duration_seconds", 5.0)))
        profile = QUALITY_PROFILES.get(str(quality).upper(), QUALITY_PROFILES["FINAL"])
        rw, rh, render_fps = _fit_profile(profile, self.output_width, self.output_height)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        silent_path = output_path.with_name(f"{output_path.stem}.silent.mp4")
        base = _load_background(background_path, rw, rh, int(scene.get("seed", 42)), scene)
        world = _World(
            scene, rw, rh, base, character_sheet or {},
            _audio_envelope(narration_path, duration, render_fps), render_fps,
        )

        command = [
            settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{rw}x{rh}",
            "-r", str(render_fps), "-i", "-", "-an",
            "-c:v", settings.video_codec, "-preset", settings.video_preset,
            "-crf", str(settings.video_crf), "-pix_fmt", "yuv420p",
            "-vf", f"scale={self.output_width}:{self.output_height}:flags=lanczos,fps={self.output_fps}",
            str(silent_path),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdin is not None
        try:
            frame_count = max(1, round(duration * render_fps))
            for frame_index in range(frame_count):
                t = min(frame_index / render_fps, duration)
                process.stdin.write(world.frame(t, duration).convert("RGB").tobytes())
            process.stdin.close()
            stderr = process.stderr.read() if process.stderr else b""
            code = process.wait()
            if code:
                raise RuntimeError(f"Animated frame encoding failed: {stderr.decode(errors='replace')[-500:]}")
        except Exception:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            process.kill()
            process.wait()
            raise

        self._mux_audio(silent_path, output_path, duration, narration_path, sfx_path)
        silent_path.unlink(missing_ok=True)
        return output_path

    def _mux_audio(
        self, silent_path: Path, output_path: Path, duration: float,
        narration_path: Path | None, sfx_path: Path | None,
    ) -> None:
        command = [settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-i", str(silent_path)]
        has_narration = bool(narration_path and narration_path.exists())
        if has_narration:
            command.extend(["-i", str(narration_path)])
        else:
            command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
        has_sfx = bool(sfx_path and sfx_path.exists())
        if has_sfx:
            command.extend(["-i", str(sfx_path)])
        filters = ["[1:a]apad[narr]"]
        audio_map = "[narr]"
        if has_sfx:
            filters.extend([
                "[2:a]volume=0.58[sfx]",
                "[narr][sfx]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            ])
            audio_map = "[aout]"
        command.extend([
            "-filter_complex", ";".join(filters), "-map", "0:v", "-map", audio_map,
            "-c:v", "copy", "-c:a", settings.audio_codec, "-t", f"{duration:.3f}",
            str(output_path),
        ])
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"Animated audio mux failed: {result.stderr[-500:]}")


class _World:
    def __init__(
        self, scene: dict, width: int, height: int, base: Image.Image,
        character_sheet: dict, audio_envelope: list[float], render_fps: int,
    ) -> None:
        self.scene = scene
        self.width = width
        self.height = height
        self.base = base
        self.character_sheet = character_sheet
        self.audio_envelope = audio_envelope
        self.render_fps = render_fps
        self.seed = int(scene.get("seed", 42))
        self.environment_kind = _environment_kind(scene)
        self.visual_quality = str(scene.get("visual_quality", "PRODUCTION")).upper()
        self.environment_layers = _load_art_layers(scene.get("environment_assets") or {}, width, height)
        self.environment_actors = _load_actor_layers(scene.get("environment_actors") or {}, width, height)
        self.character_rig = None
        rig_manifest = scene.get("character_rig_manifest")
        if rig_manifest and Path(str(rig_manifest)).exists():
            from app.video.illustrated_rig import IllustratedCharacterRig
            self.character_rig = IllustratedCharacterRig(
                Path(str(rig_manifest)), scene.get("character_expressions") or {}
            )
        rng = random.Random(self.seed)
        self.fog = [(rng.uniform(-0.2, 1.0), rng.uniform(0.38, 0.92), rng.uniform(0.12, 0.34), rng.uniform(0.008, 0.024)) for _ in range(13)]
        self.particles = [(rng.random(), rng.random(), rng.uniform(0.6, 2.3), rng.uniform(0.2, 1.0)) for _ in range(55)]
        self.trees = _tree_layout(rng)
        self.vignette = _vignette_mask(width, height)
        self.grain = _grain_overlay(width, height, self.seed)

    def frame(self, t: float, duration: float) -> Image.Image:
        shot = _active_shot(self.scene.get("shots") or [], t, duration)
        local = max(0.0, min(1.0, (t - float(shot.get("start", 0))) / max(float(shot.get("duration", duration)), 0.01)))
        eased = _ease(local)
        camera = _camera_state(shot, eased, t)
        frame = _camera_frame(self.base, self.width, self.height, camera)
        self._composite_art_layer(frame, "midground", t, camera, 0.28)
        draw = ImageDraw.Draw(frame, "RGBA")

        # Environment is deliberately separated into depth bands. Their motion
        # differs with camera displacement, producing real parallax.
        self._distant_layer(draw, t, camera)
        self._midground_layer(draw, t, camera)
        self._light_layer(frame, t, shot)
        self._ground_layer(draw, t, camera)
        self._environment_actors(frame, t, duration, camera)
        self._interaction_layer(frame, shot, local)
        self._character_layer(frame, draw, t, duration, shot, local)
        self._composite_art_layer(frame, "foreground", t, camera, 0.82)
        self._foreground_layer(draw, t, camera)
        self._atmosphere(frame, t)
        self._grade(frame, shot, t, duration)
        return frame

    def _environment_actors(self, frame: Image.Image, t: float, duration: float, camera: dict) -> None:
        """Move discrete painted environment elements independently of camera."""
        taxi = self.environment_actors.get("vehicle")
        if taxi is not None:
            travel = ((t / max(duration, .01)) * 1.55 - .34) * self.width
            x = round(travel - camera["x"] * .48)
            y = round(self.height * .67)
            # Small suspension motion is tied to wheel cadence, not camera.
            y += round(math.sin(t * 8.2) * self.height * .0025)
            frame.alpha_composite(taxi, (x, y))

    def _interaction_layer(self, frame: Image.Image, shot: dict, local: float) -> None:
        """Animate real pixels from a declared prop region (for example a door)."""
        if str(shot.get("action")) not in {"open_door", "close_door"}:
            return
        raw = (self.scene.get("interactive_regions") or {}).get("door")
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return
        x1, y1, x2, y2 = (
            round(float(raw[0]) * self.width), round(float(raw[1]) * self.height),
            round(float(raw[2]) * self.width), round(float(raw[3]) * self.height),
        )
        if x2 <= x1 or y2 <= y1:
            return
        panel = frame.crop((x1, y1, x2, y2)).convert("RGBA")
        progress = _ease(min(1.0, max(0.0, local * 1.65)))
        if str(shot.get("action")) == "close_door":
            progress = 1.0 - progress
        # Replace the closed panel with a shaded interior, then foreshorten the
        # source-painted panel around its left hinge. No synthetic door is drawn.
        interior = ImageEnhance.Brightness(panel).enhance(0.16)
        frame.alpha_composite(interior, (x1, y1))
        open_width = max(3, round(panel.width * (1.0 - progress * 0.82)))
        moving_panel = panel.resize((open_width, panel.height), Image.Resampling.BICUBIC)
        shade = Image.new("RGBA", moving_panel.size, (4, 10, 13, round(24 * progress)))
        moving_panel = Image.alpha_composite(moving_panel, shade)
        frame.alpha_composite(moving_panel, (x1, y1))

    def _distant_layer(self, draw: ImageDraw.ImageDraw, t: float, camera: dict) -> None:
        drift = camera["x"] * 0.12
        if self.visual_quality != "DEBUG":
            return
        if self.environment_kind != "forest":
            self._graphic_depth(draw, t, drift, distant=True)
            return
        horizon = int(self.height * 0.55)
        for x, scale, shade, depth in self.trees[0]:
            px = int(x * self.width - drift)
            h = int(self.height * scale)
            _tree(draw, px, horizon, h, (8 + shade, 20 + shade, 25 + shade, 205), depth)

    def _midground_layer(self, draw: ImageDraw.ImageDraw, t: float, camera: dict) -> None:
        drift = camera["x"] * 0.38
        if self.visual_quality != "DEBUG":
            return
        if self.environment_kind != "forest":
            self._graphic_depth(draw, t, drift, distant=False)
            return
        horizon = int(self.height * 0.76)
        for x, scale, shade, depth in self.trees[1]:
            sway = math.sin(t * 0.7 + x * 8) * self.width * 0.002
            px = int(x * self.width - drift + sway)
            h = int(self.height * scale)
            _tree(draw, px, horizon, h, (5 + shade, 14 + shade, 17 + shade, 238), depth)

    def _ground_layer(self, draw: ImageDraw.ImageDraw, t: float, camera: dict) -> None:
        if self.visual_quality != "DEBUG":
            return
        if self.environment_kind != "forest":
            if self.environment_kind == "evidence":
                y = int(self.height * 0.86)
                draw.rectangle((0, y, self.width, self.height), fill=(5, 9, 12, 72))
            return
        y = int(self.height * 0.73)
        draw.polygon([(0, y), (self.width, y - 10), (self.width, self.height), (0, self.height)], fill=(4, 10, 12, 188))
        for index in range(16):
            x = int((index / 15 * 1.25 * self.width - camera["x"] * 0.58) % (self.width * 1.25) - self.width * 0.12)
            yy = int(y + (index % 4) * self.height * 0.045)
            draw.line((x, yy, x + self.width * 0.04, yy - self.height * 0.015), fill=(35, 46, 36, 105), width=max(1, self.width // 500))

    def _foreground_layer(self, draw: ImageDraw.ImageDraw, t: float, camera: dict) -> None:
        if self.visual_quality != "DEBUG":
            return
        if self.environment_kind != "forest":
            # A few translucent edge shapes supply foreground depth without
            # changing the subject of maps, documents, or evidence plates.
            offset = math.sin(t * 0.34) * self.width * 0.008
            draw.polygon([(0, 0), (self.width * 0.055 + offset, 0), (self.width * 0.025 + offset, self.height), (0, self.height)], fill=(1, 5, 7, 76))
            draw.polygon([(self.width, 0), (self.width * 0.955 + offset, 0), (self.width * 0.98 + offset, self.height), (self.width, self.height)], fill=(1, 5, 7, 76))
            return
        for side in (-1, 1):
            x = int((0.03 if side < 0 else 0.97) * self.width - camera["x"] * 0.9)
            bend = int(math.sin(t * 0.55 + side) * self.width * 0.008)
            draw.line((x, self.height, x + bend, self.height * 0.18), fill=(2, 7, 8, 245), width=max(18, self.width // 24))
            for branch in range(5):
                yy = int(self.height * (0.34 + branch * 0.11))
                direction = -side if branch % 2 else side
                draw.line((x + bend, yy, x + direction * self.width * 0.13, yy - self.height * 0.08), fill=(2, 8, 9, 230), width=max(5, self.width // 120))

    def _composite_art_layer(
        self, frame: Image.Image, name: str, t: float, camera: dict, depth_speed: float
    ) -> None:
        layer = self.environment_layers.get(name)
        if layer is None:
            return
        dx = round(-camera["x"] * depth_speed + math.sin(t * 0.22 + depth_speed) * 4 * depth_speed)
        dy = round(-camera["y"] * depth_speed * 0.45)
        stage = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        stage.alpha_composite(layer, (dx, dy))
        frame.alpha_composite(stage)

    def _graphic_depth(self, draw: ImageDraw.ImageDraw, t: float, drift: float, *, distant: bool) -> None:
        alpha = 30 if distant else 58
        speed = 0.14 if distant else 0.42
        offset = drift * speed
        if self.environment_kind == "map":
            for index in range(7):
                y = self.height * (0.18 + index * 0.105) + math.sin(t * 0.33 + index) * 7
                points = []
                for step in range(10):
                    x = step / 9 * self.width - offset
                    yy = y + math.sin(step * 1.6 + index) * self.height * 0.018
                    points.append((x, yy))
                draw.line(points, fill=(216, 171, 84, alpha), width=max(1, self.width // 640))
            return
        if self.environment_kind == "evidence":
            for index in range(5):
                x = self.width * (0.08 + index * 0.22) - offset
                y = self.height * (0.12 + (index % 2) * 0.46)
                w, h = self.width * 0.13, self.height * 0.19
                draw.rounded_rectangle((x, y, x + w, y + h), radius=4, outline=(225, 212, 177, alpha), width=max(1, self.width // 500))
            return
        if self.environment_kind == "city":
            baseline = self.height * 0.78
            for index in range(13):
                x = index / 12 * self.width - offset
                h = self.height * (0.12 + (index * 7 % 5) * 0.045)
                draw.rectangle((x, baseline - h, x + self.width * 0.065, baseline), fill=(6, 14, 19, alpha + 35))
            return
        # Neutral cinematic depth bands.
        for index in range(5):
            x = self.width * (index * 0.27 - 0.1) - offset
            draw.polygon([(x, self.height), (x + self.width * 0.18, self.height * 0.2), (x + self.width * 0.31, self.height)], fill=(4, 12, 16, alpha))

    def _light_layer(self, frame: Image.Image, t: float, shot: dict) -> None:
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        pulse = 0.88 + 0.12 * math.sin(t * 1.3)
        origin = (int(self.width * 0.72), int(self.height * 0.05))
        draw.polygon([origin, (int(self.width * 0.47), self.height), (int(self.width * 0.88), self.height)], fill=(122, 165, 159, int(28 * pulse)))
        draw.ellipse((origin[0] - 28, origin[1] - 28, origin[0] + 28, origin[1] + 28), fill=(206, 226, 211, int(65 * pulse)))
        overlay = overlay.filter(ImageFilter.GaussianBlur(max(8, self.width // 80)))
        frame.alpha_composite(overlay)

    def _character_layer(self, frame: Image.Image, draw: ImageDraw.ImageDraw, t: float, duration: float, shot: dict, local: float) -> None:
        characters = (
            shot.get("characters") or []
            if "characters" in shot
            else ([] if not self.scene.get("character_name") else [self.scene["character_name"]])
        )
        if not characters:
            return
        shot_type = shot.get("shot_type", "medium")
        base_scale = {"wide": 0.36, "medium": 0.55, "closeup": 0.92, "insert": 0.46, "rear": 0.58, "over_shoulder": 0.72}.get(shot_type, 0.52)
        action = str(shot.get("action", "react"))
        walking = action in {"walk", "walking", "run", "walk_across", "enter", "enter_room", "exit_room"} or "walk" in str(self.scene.get("character_motion", ""))
        # Blocking (start/end screen position) is scene- and shot-specific so a
        # walk never traces the same fixed path twice; see app/video/blocking.py.
        blocking = shot.get("character_position") or character_blocking(action, shot_type, self.seed)
        start_x = self.width * float(blocking.get("start_x", 0.56))
        end_x = self.width * float(blocking.get("end_x", 0.56))
        if walking:
            progress = local
            # Locomotion is allowed only alongside the gait below. A production
            # walk never has a root-position-only rendering path.
            cx = start_x + (end_x - start_x) * _ease(progress)
        elif action == "stop":
            # A short ease-out makes the deceleration readable, followed by a
            # held final position; camera movement is measured separately.
            stop_progress = 1.0 - (1.0 - min(local * 1.8, 1.0)) ** 3
            cx = start_x + (end_x - start_x) * stop_progress
        else:
            cx = (start_x + end_x) / 2.0 + self.width * 0.015 * math.sin(t * 0.7)
        if action in {"open_door", "close_door", "interact"}:
            cx = self.width * 0.64
        if shot_type == "closeup":
            cx = (start_x + end_x) / 2.0
        phase = t * (9.5 if "run" in action else 6.0)
        expression = str(shot.get("expression", "neutral"))
        envelope_index = min(int(t * self.render_fps), max(len(self.audio_envelope) - 1, 0))
        mouth_open = self.audio_envelope[envelope_index] if self.audio_envelope else 0.0
        if self.character_rig is not None:
            closeup = shot_type == "closeup"
            illustrated_height = round(self.height * (1.65 if closeup else base_scale * 1.72))
            if walking:
                shot_seconds = max(float(shot.get("duration", duration)), .01)
                travel_pixels = self.width * .48
                stride_pixels = max(28.0, illustrated_height * .31)
                cycles = max(1.0, travel_pixels / stride_pixels)
                phase = local * math.tau * cycles
            actor = self.character_rig.render(
                illustrated_height,
                phase=phase,
                action=action,
                expression=expression,
                head_turn=(local if action in {"turn_head", "look_around", "react", "stop"} else 0.0),
                breathing=1.0 + 0.012 * math.sin(t * 3.0),
                closeup=closeup,
                progress=local,
                mouth_open=mouth_open,
            )
            shadow = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow, "RGBA")
            shadow_width = actor.width * (0.27 if closeup else 0.34)
            shadow_draw.ellipse(
                (cx - shadow_width, self.height * 0.91, cx + shadow_width, self.height * 0.965),
                fill=(0, 3, 6, 118 if not closeup else 45),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(max(5, self.width // 110)))
            frame.alpha_composite(shadow)
            actor_x = round(cx - actor.width / 2)
            actor_y = round(self.height * 0.05) if closeup else round(self.height * 0.95 - actor.height)
            # Foreground haze partially veils the lower body and visually seats
            # the painted character inside the environment.
            frame.alpha_composite(actor, (actor_x, actor_y))
            return
        raise CharacterGenerationError(DIFFUSION_FAILURE)

    def _atmosphere(self, frame: Image.Image, t: float) -> None:
        effect = next(
            (
                layer.get("motion")
                for layer in self.scene.get("layers", [])
                if layer.get("type") == "fx"
            ),
            "fog",
        )
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")
        if effect in {"fog", "smoke", "dust"}:
            for x, y, radius, speed in self.fog:
                px = ((x + t * speed) % 1.35 - 0.15) * self.width
                py = y * self.height + math.sin(t * 0.3 + x * 9) * self.height * 0.025
                rx, ry = radius * self.width, radius * self.height * 0.36
                draw.ellipse((px - rx, py - ry, px + rx, py + ry), fill=(175, 196, 194, 18 if effect == "fog" else 11))
            overlay = overlay.filter(ImageFilter.GaussianBlur(max(10, self.width // 55)))
        elif effect in {"rain", "snow"}:
            for x, y, speed, size in self.particles:
                px = ((x + t * 0.03) % 1.0) * self.width
                py = ((y + t * speed * (0.18 if effect == "rain" else 0.045)) % 1.0) * self.height
                if effect == "rain":
                    draw.line((px, py, px - 5, py + 19 * size), fill=(158, 196, 214, 105), width=1)
                else:
                    draw.ellipse((px, py, px + 3 * size, py + 3 * size), fill=(230, 240, 244, 170))
        frame.alpha_composite(overlay)

    def _grade(self, frame: Image.Image, shot: dict, t: float, duration: float) -> None:
        # Coherent cool grade, restrained grain, smooth vignette, and letterbox.
        cool = Image.new("RGBA", frame.size, (18, 47, 58, 0))
        cool.putalpha(17)
        frame.alpha_composite(cool)
        frame.alpha_composite(self.grain)
        vignette = Image.new("RGBA", frame.size, (0, 2, 5, 0))
        vignette.putalpha(self.vignette)
        frame.alpha_composite(vignette)
        draw = ImageDraw.Draw(frame, "RGBA")
        bar = max(0, int(self.height * 0.035))
        draw.rectangle((0, 0, self.width, bar), fill=(0, 0, 0, 235))
        draw.rectangle((0, self.height - bar, self.width, self.height), fill=(0, 0, 0, 235))
        if bool(self.scene.get("fade_out")) and t > duration - 0.38:
            fade = min(1.0, (t - (duration - 0.38)) / 0.38)
            draw.rectangle((0, 0, self.width, self.height), fill=(0, 0, 0, round(255 * _ease(fade))))


def _draw_puppet(
    target: Image.Image, anchor: tuple[float, float], height: float, *,
    phase: float, walking: bool, expression: str, rear: bool, identity: str,
    breathing: float, head_turn: float, mouth_open: float,
) -> None:
    scale = height / 520.0
    width = int(270 * scale)
    h = int(560 * scale)
    puppet = Image.new("RGBA", (max(width, 2), max(h, 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(puppet, "RGBA")
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    coats = [(31, 64, 54), (48, 55, 71), (82, 46, 37), (41, 49, 47)]
    skins = [(111, 73, 52), (151, 103, 72), (190, 139, 98), (222, 174, 126)]
    coat, skin = coats[digest[0] % len(coats)], skins[digest[1] % len(skins)]
    trousers = (21 + digest[4] % 13, 28 + digest[5] % 12, 31 + digest[6] % 15)
    hair = (18 + digest[2] % 18, 16 + digest[3] % 12, 14)
    cx = puppet.width / 2
    hip_y = 340 * scale
    shoulder_y = 190 * scale
    gait = math.sin(phase) if walking else math.sin(phase * 0.28) * 0.08
    bob = abs(math.sin(phase)) * 7 * scale if walking else math.sin(phase * 0.35) * 2 * scale

    def limb(origin, length, angle, color, thickness):
        end = (origin[0] + math.sin(angle) * length, origin[1] + math.cos(angle) * length)
        draw.line((origin, end), fill=(*color, 255), width=max(2, int(thickness * scale)))
        draw.ellipse((end[0] - 6 * scale, end[1] - 6 * scale, end[0] + 6 * scale, end[1] + 6 * scale), fill=(*color, 255))
        return end

    # Independent legs and arms create an actual articulated walk cycle.
    leg_a = gait * 0.48
    leg_b = -gait * 0.48
    foot1 = limb((cx - 23 * scale, hip_y - bob), 160 * scale, leg_a, _shade(trousers, 0.76), 34)
    foot2 = limb((cx + 23 * scale, hip_y - bob), 160 * scale, leg_b, trousers, 34)
    for foot, direction in ((foot1, gait), (foot2, -gait)):
        draw.line((foot[0], foot[1], foot[0] + (25 + direction * 10) * scale, foot[1]), fill=(10, 15, 16, 255), width=max(3, int(17 * scale)))
    arm_a = -gait * 0.62 if walking else math.sin(phase * 0.4) * 0.06
    arm_b = gait * 0.62 if walking else -math.sin(phase * 0.4) * 0.06
    hand1 = limb((cx - 54 * scale, shoulder_y), 155 * scale, arm_a, _shade(coat, 0.78), 30)
    hand2 = limb((cx + 54 * scale, shoulder_y), 155 * scale, arm_b, _shade(coat, 0.62), 30)
    for hand in (hand1, hand2):
        draw.ellipse((hand[0] - 8 * scale, hand[1] - 9 * scale, hand[0] + 8 * scale, hand[1] + 9 * scale), fill=(*skin, 255))

    torso_w = 116 * scale * breathing
    draw.polygon([
        (cx - torso_w / 2, shoulder_y - bob), (cx + torso_w / 2, shoulder_y - bob),
        (cx + 68 * scale, hip_y - bob), (cx - 68 * scale, hip_y - bob),
    ], fill=(*coat, 255))
    # Collar, lapels, seams, and pockets prevent the puppet reading as a card.
    draw.polygon([(cx - 32 * scale, shoulder_y), (cx - 4 * scale, shoulder_y + 48 * scale), (cx, shoulder_y + 11 * scale)], fill=(*_shade(coat, 1.22), 245))
    draw.polygon([(cx + 32 * scale, shoulder_y), (cx + 4 * scale, shoulder_y + 48 * scale), (cx, shoulder_y + 11 * scale)], fill=(*_shade(coat, 0.82), 245))
    draw.line((cx, shoulder_y, cx, hip_y - 10 * scale), fill=(167, 119, 57, 185), width=max(1, int(3 * scale)))
    draw.line((cx - 52 * scale, hip_y - 70 * scale, cx - 17 * scale, hip_y - 76 * scale), fill=(*_shade(coat, 0.58), 190), width=max(1, int(3 * scale)))
    neck_y = shoulder_y - 24 * scale - bob
    draw.rectangle((cx - 17 * scale, neck_y, cx + 17 * scale, shoulder_y), fill=(*skin, 255))
    head_rx = 46 * scale * (0.72 + 0.28 * abs(math.cos(head_turn * math.pi / 2)))
    head_box = (cx - head_rx, neck_y - 99 * scale, cx + head_rx, neck_y + 5 * scale)
    draw.ellipse(head_box, fill=(*skin, 255))
    draw.ellipse((head_box[0] - 5 * scale, neck_y - 62 * scale, head_box[0] + 9 * scale, neck_y - 34 * scale), fill=(*_shade(skin, 0.9), 255))
    draw.ellipse((head_box[2] - 9 * scale, neck_y - 62 * scale, head_box[2] + 5 * scale, neck_y - 34 * scale), fill=(*_shade(skin, 0.9), 255))
    draw.pieslice((head_box[0] - 4 * scale, head_box[1] - 9 * scale, head_box[2] + 4 * scale, head_box[3] - 20 * scale), 178, 360, fill=(*hair, 255))
    if not rear:
        eye_y = neck_y - 54 * scale
        eye_open = 1.65 if expression in {"fear", "surprised"} else 1.0
        blink = abs(math.sin(phase * 0.23)) > 0.985
        eye_h = (1 if blink else 5 * eye_open) * scale
        eye_dx = 19 * scale * max(0.4, math.cos(head_turn * math.pi / 2))
        for ex in (cx - eye_dx, cx + eye_dx):
            draw.ellipse((ex - 6 * scale, eye_y - eye_h, ex + 6 * scale, eye_y + eye_h), fill=(229, 225, 205, 255))
            if not blink:
                draw.ellipse((ex - 2 * scale, eye_y - 2 * scale, ex + 2 * scale, eye_y + 2 * scale), fill=(18, 20, 19, 255))
        brow_tilt = -4 * scale if expression in {"fear", "surprised"} else 0
        draw.line((cx - eye_dx - 7 * scale, eye_y - 13 * scale, cx - eye_dx + 7 * scale, eye_y - 13 * scale + brow_tilt), fill=(*hair, 225), width=max(1, int(2.5 * scale)))
        draw.line((cx + eye_dx - 7 * scale, eye_y - 13 * scale + brow_tilt, cx + eye_dx + 7 * scale, eye_y - 13 * scale), fill=(*hair, 225), width=max(1, int(2.5 * scale)))
        draw.line((cx, eye_y + 3 * scale, cx - 3 * scale, eye_y + 18 * scale), fill=(*_shade(skin, 0.72), 155), width=max(1, int(1.5 * scale)))
        mouth_y = neck_y - 19 * scale
        if mouth_open > 0.08:
            viseme = int(phase * 1.7) % 3
            mouth_w = (8, 13, 10)[viseme] * scale * (0.75 + mouth_open)
            mouth_h = (5, 4, 9)[viseme] * scale * (0.55 + mouth_open)
            draw.ellipse((cx - mouth_w, mouth_y - mouth_h, cx + mouth_w, mouth_y + mouth_h), fill=(45, 19, 22, 235))
        elif expression in {"fear", "surprised"}:
            draw.ellipse((cx - 7 * scale, mouth_y - 4 * scale, cx + 7 * scale, mouth_y + 11 * scale), fill=(48, 22, 22, 225))
        elif expression == "happy":
            draw.arc((cx - 14 * scale, mouth_y - 8 * scale, cx + 14 * scale, mouth_y + 12 * scale), 5, 175, fill=(70, 34, 29, 235), width=max(1, int(2 * scale)))
        else:
            draw.line((cx - 10 * scale, mouth_y, cx + 10 * scale, mouth_y), fill=(70, 34, 29, 220), width=max(1, int(2 * scale)))

    # Soft contact shadow is a separate composited layer.
    shadow = Image.new("RGBA", target.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    ax, ay = anchor
    sd.ellipse((ax - width * 0.33, ay - height * 0.025, ax + width * 0.34, ay + height * 0.025), fill=(0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(3, int(9 * scale))))
    target.alpha_composite(shadow)
    x = int(ax - puppet.width / 2)
    y = int(ay - puppet.height)
    target.alpha_composite(puppet, (x, y))


def _load_background(path: Path | None, width: int, height: int, seed: int, scene: dict) -> Image.Image:
    if path and path.exists():
        source = Image.open(path).convert("RGB")
        fitted = ImageOps.fit(source, (width, height), Image.Resampling.LANCZOS)
        fitted = ImageEnhance.Color(fitted).enhance(0.68)
        fitted = ImageEnhance.Contrast(fitted).enhance(1.14)
        return fitted.convert("RGBA")
    # Explicit procedural animation fallback, never a static black frame.
    image = Image.new("RGBA", (width, height), (5, 12, 21, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(height):
        p = y / max(height - 1, 1)
        draw.line((0, y, width, y), fill=(int(6 + p * 6), int(15 + p * 8), int(27 + p * 4), 255))
    draw.ellipse((width * 0.68, -height * 0.08, width * 0.82, height * 0.17), fill=(169, 191, 190, 105))
    return image


def _load_art_layers(raw: dict, width: int, height: int) -> dict[str, Image.Image]:
    layers: dict[str, Image.Image] = {}
    for name, value in raw.items():
        path = Path(str(value))
        if not path.exists() or name not in {"distant", "midground", "foreground"}:
            continue
        source = Image.open(path).convert("RGBA")
        layers[name] = ImageOps.fit(source, (width, height), Image.Resampling.LANCZOS)
    return layers


def _load_actor_layers(raw: dict, width: int, height: int) -> dict[str, Image.Image]:
    """Load discrete painted environment actors (for example a passing vehicle).

    Unlike full-frame art layers these keep their own aspect ratio and are
    scaled relative to frame height instead of being cropped to fill it.
    """
    layers: dict[str, Image.Image] = {}
    for name, value in raw.items():
        path = Path(str(value))
        if not path.exists():
            continue
        source = Image.open(path).convert("RGBA")
        scale = (height * 0.12) / max(source.height, 1)
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        layers[name] = source.resize(size, Image.Resampling.LANCZOS)
    return layers


def _vignette_mask(width: int, height: int) -> Image.Image:
    small_w, small_h = max(64, width // 8), max(36, height // 8)
    mask = Image.new("L", (small_w, small_h), 0)
    pixels = mask.load()
    for y in range(small_h):
        ny = (y / max(small_h - 1, 1) - 0.5) / 0.55
        for x in range(small_w):
            nx = (x / max(small_w - 1, 1) - 0.5) / 0.68
            distance = math.sqrt(nx * nx + ny * ny)
            pixels[x, y] = round(88 * _ease(max(0.0, min(1.0, (distance - 0.42) / 0.62))))
    return mask.resize((width, height), Image.Resampling.BICUBIC)


def _grain_overlay(width: int, height: int, seed: int) -> Image.Image:
    rng = random.Random(seed ^ 0xA17D1E)
    small = Image.new("L", (max(64, width // 4), max(36, height // 4)))
    small.putdata([rng.randint(92, 164) for _ in range(small.width * small.height)])
    grain = small.resize((width, height), Image.Resampling.BILINEAR)
    overlay = Image.new("RGBA", (width, height), (205, 213, 204, 0))
    overlay.putalpha(grain.point(lambda value: max(0, min(10, abs(value - 128) // 5))))
    return overlay


def _fit_profile(profile: tuple[int, int, int], output_width: int, output_height: int) -> tuple[int, int, int]:
    base_w, _, fps = profile
    ratio = output_width / output_height
    width = min(base_w, output_width)
    height = max(2, round(width / ratio / 2) * 2)
    return width, height, min(fps, 30)


def _audio_envelope(path: Path | None, duration: float, fps: int) -> list[float]:
    """Create deterministic amplitude-driven mouth movement from narration."""
    frame_count = max(1, round(duration * fps))
    if not path or not path.exists():
        return [0.0] * frame_count
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(path).set_channels(1)
        frame_ms = 1000.0 / fps
        raw = []
        for index in range(frame_count):
            chunk = audio[round(index * frame_ms):round((index + 1) * frame_ms)]
            raw.append(float(chunk.rms))
        peak = max(raw) or 1.0
        return [min(1.0, max(0.0, (value / peak - 0.06) * 1.35)) for value in raw]
    except Exception:
        return [0.0] * frame_count


def _active_shot(shots: list[dict], t: float, duration: float) -> dict:
    for shot in shots:
        if float(shot.get("start", 0)) <= t < float(shot.get("start", 0)) + float(shot.get("duration", 0)):
            return shot
    return shots[-1] if shots else {"start": 0.0, "duration": duration, "shot_type": "wide", "camera": {"move": "slow_push"}}


def _camera_state(shot: dict, eased: float, t: float) -> dict:
    camera = shot.get("camera") or {}
    start, end = camera.get("start") or {}, camera.get("end") or {}
    move = camera.get("move", "slow_push")
    zoom = _lerp(float(start.get("zoom", 1.0)), float(end.get("zoom", 1.08)), eased)
    x = _lerp(float(start.get("x", 0)), float(end.get("x", 0)), eased)
    y = _lerp(float(start.get("y", 0)), float(end.get("y", 0)), eased)
    if move in {"pan_right", "track_character", "follow_character"}:
        x += eased * 105
    elif move == "pan_left":
        x -= eased * 105
    elif move == "pan_up":
        y -= eased * 65
    elif move == "pan_down":
        y += eased * 65
    elif move in {"handheld", "shake"}:
        strength = 5 if move == "handheld" else 11
        x += math.sin(t * 14.7) * strength
        y += math.sin(t * 11.3 + 1.2) * strength * 0.55
    elif move == "orbit_simulation":
        x += math.sin(eased * math.pi) * 85
        zoom += math.sin(eased * math.pi) * 0.04
    return {"x": x, "y": y, "zoom": max(1.0, zoom)}


def _camera_frame(base: Image.Image, width: int, height: int, camera: dict) -> Image.Image:
    zoom = camera["zoom"]
    crop_w, crop_h = width / zoom, height / zoom
    cx = width / 2 + camera["x"]
    cy = height / 2 + camera["y"]
    left = max(0, min(width - crop_w, cx - crop_w / 2))
    top = max(0, min(height - crop_h, cy - crop_h / 2))
    crop = base.crop((round(left), round(top), round(left + crop_w), round(top + crop_h)))
    return crop.resize((width, height), Image.Resampling.BICUBIC).convert("RGBA")


def _tree_layout(rng: random.Random) -> list[list[tuple[float, float, int, int]]]:
    layers = []
    for count, lo, hi in ((18, 0.20, 0.42), (13, 0.38, 0.70)):
        layer = []
        for index in range(count):
            layer.append((index / max(count - 1, 1) + rng.uniform(-0.04, 0.04), rng.uniform(lo, hi), rng.randint(0, 8), rng.randint(2, 5)))
        layers.append(layer)
    return layers


def _environment_kind(scene: dict) -> str:
    text = " ".join(str(scene.get(key, "")) for key in ("visual_description", "image_prompt", "asset_type")).lower()
    if any(word in text for word in ("forest", "woods", "pine", "tree", "jungle")):
        return "forest"
    if any(word in text for word in ("map", "route", "topographic", "geography")):
        return "map"
    if any(word in text for word in ("evidence", "document", "newspaper", "logbook", "paper", "archive")):
        return "evidence"
    if any(word in text for word in ("city", "street", "building", "skyline", "town")):
        return "city"
    return "neutral"


def _tree(draw: ImageDraw.ImageDraw, x: int, ground_y: int, height: int, color: tuple[int, int, int, int], depth: int) -> None:
    trunk = max(3, height // 26)
    draw.rectangle((x - trunk // 2, ground_y - height, x + trunk // 2, ground_y), fill=color)
    crown = (max(1, color[0] + 3), max(1, color[1] + 7), max(1, color[2] + 4), color[3])
    for index, ratio in enumerate((0.18, 0.34, 0.50, 0.66)):
        yy = ground_y - height + int(height * ratio)
        half = int(height * (0.11 + index * 0.025))
        draw.polygon([(x, yy - int(height * 0.16)), (x - half, yy + int(height * 0.11)), (x + half, yy + int(height * 0.11))], fill=crown)


def _ease(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def _lerp(start: float, end: float, value: float) -> float:
    return start + (end - start) * value


def _shade(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return (
        max(0, min(255, int(color[0] * amount))),
        max(0, min(255, int(color[1] * amount))),
        max(0, min(255, int(color[2] * amount))),
    )
