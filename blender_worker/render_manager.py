"""Resumable frame rendering and FFmpeg assembly."""
import subprocess
from pathlib import Path

import bpy


def configure(scene, plan, quality):
    preview = quality == "PREVIEW"
    scene.render.engine = "BLENDER_WORKBENCH" if preview else "BLENDER_EEVEE"
    scene.render.resolution_x = 640 if preview else int(plan["render"].get("width", 1920))
    scene.render.resolution_y = 360 if preview else int(plan["render"].get("height", 1080))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 88 if preview else 96
    scene.render.film_transparent = False
    if preview:
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "MATERIAL"
        shading.show_shadows = True
        shading.show_cavity = True
        shading.cavity_type = "BOTH"
        shading.show_specular_highlight = False
        shading.show_object_outline = True
        shading.background_type = "WORLD"


def render_frames(scene, output, fps):
    frames_dir = Path(output).with_suffix("").parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for frame in range(scene.frame_start, scene.frame_end + 1):
        path = frames_dir / f"frame_{frame:04d}.jpg"
        if path.exists() and path.stat().st_size > 5000:
            continue
        scene.frame_set(frame)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%04d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "20", str(output),
    ], check=True)
