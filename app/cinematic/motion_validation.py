"""Pixel- and telemetry-based acceptance checks for the 10-second proof."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat


SHOTS = (
    ("shot_01_exterior_dolly", 1, 45, False),
    ("shot_02_articulated_walk", 46, 105, True),
    ("shot_03_look_and_sit", 106, 150, True),
)


def analyze_motion(frames_dir: Path, telemetry_path: Path, output_path: Path) -> dict:
    telemetry = {item["frame"]: item for item in json.loads(telemetry_path.read_text(encoding="utf-8"))}
    reports = []
    for shot_id, start, end, character_required in SHOTS:
        differences, changed = [], []
        background_differences, foreground_differences = [], []
        previous = Image.open(frames_dir / f"frame_{start:04d}.png").convert("RGB")
        width, height = previous.size
        for frame in range(start + 1, end + 1):
            current = Image.open(frames_dir / f"frame_{frame:04d}.png").convert("RGB")
            delta = ImageChops.difference(previous, current).convert("L")
            differences.append(ImageStat.Stat(delta).mean[0])
            histogram = delta.histogram()
            changed.append(sum(histogram[7:]) / (width * height) * 100)
            background_differences.append(ImageStat.Stat(delta.crop((width//4, 0, width*3//4, height//3))).mean[0])
            foreground_differences.append(ImageStat.Stat(delta.crop((0, height*2//3, width, height))).mean[0])
            previous = current
        camera_positions = [telemetry[f]["camera"] for f in range(start, end + 1)]
        camera_travel = _distance(camera_positions[0], camera_positions[-1])
        relative_joint_motion = _joint_motion(telemetry, start, end)
        head_positions = [telemetry[f]["joints"]["head"] for f in range(start, end+1)]
        composed_percentage = sum(0 <= x <= width and 0 <= y <= height for x, y in head_positions) / len(head_positions) * 100
        mean_difference = sum(differences) / max(1, len(differences))
        motion_percentage = sum(changed) / max(1, len(changed))
        bg_motion = sum(background_differences) / max(1, len(background_differences))
        fg_motion = sum(foreground_differences) / max(1, len(foreground_differences))
        character_motion = relative_joint_motion > (1.3 if shot_id.endswith("walk") else .7)
        camera_motion = camera_travel > .2
        foreground_motion = fg_motion > .45
        background_motion = bg_motion > .25
        # Different regional motion plus a physical camera translation rejects a
        # single global scale/opacity transform as "parallax".
        parallax = camera_motion and foreground_motion and background_motion and abs(fg_motion-bg_motion) > .12
        motion_detected = mean_difference > .35 and motion_percentage > .8
        passed = motion_detected and camera_motion and foreground_motion and background_motion and parallax
        if character_required:
            passed = passed and character_motion and composed_percentage >= 90
        reports.append({
            "shot_id": shot_id, "frame_count": end-start+1,
            "motion_detected": motion_detected, "motion_percentage": round(motion_percentage, 3),
            "mean_pixel_difference": round(mean_difference, 3),
            "character_motion": character_motion, "character_relative_joint_motion_px": round(relative_joint_motion, 3),
            "character_composed_percentage": round(composed_percentage, 3),
            "camera_motion": camera_motion, "camera_travel_blender_units": round(camera_travel, 3),
            "foreground_motion": foreground_motion, "foreground_pixel_difference": round(fg_motion, 3),
            "background_motion": background_motion, "background_pixel_difference": round(bg_motion, 3),
            "parallax_detected": parallax,
            "global_transform_only": not character_motion and abs(fg_motion-bg_motion) <= .12,
            "animation_status": "PASS" if passed else "FAIL",
        })
    report = {
        "test": "10_second_no_audio_no_subtitles_2d25d_acceptance",
        "frame_comparison": "consecutive RGB frames; threshold > 6/255",
        "success": all(item["animation_status"] == "PASS" for item in reports),
        "shots": reports,
    }
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def create_debug_video(frames_dir: Path, telemetry_path: Path, output_path: Path, ffmpeg="ffmpeg", fps=15) -> Path:
    telemetry = {item["frame"]: item for item in json.loads(telemetry_path.read_text(encoding="utf-8"))}
    debug_dir = output_path.parent / "debug_frames"; debug_dir.mkdir(parents=True, exist_ok=True)
    colors = {"head": "#ffdd55", "upper_arm_left": "#58d6ff", "upper_arm_right": "#58d6ff",
              "upper_leg_left": "#ff6b6b", "upper_leg_right": "#ff6b6b", "foot_left": "#ffffff", "foot_right": "#ffffff"}
    previous = None
    for frame in range(1, 151):
        image = Image.open(frames_dir / f"frame_{frame:04d}.png").convert("RGB")
        draw = ImageDraw.Draw(image, "RGBA"); data = telemetry[frame]
        draw.rectangle((8, 8, 252, 76), fill=(5, 8, 12, 190), outline=(255, 188, 72, 255), width=2)
        shot = 1 if frame <= 45 else (2 if frame <= 105 else 3)
        draw.text((18, 16), f"DEBUG_2D25D  SHOT {shot}  F{frame:03d}", fill="white")
        draw.text((18, 37), f"PHYSICAL CAMERA xyz {data['camera']}", fill=(210, 232, 230, 255))
        draw.text((18, 57), "depth  BG -10 | MID -4 | CHAR 0 | FORE +8", fill=(255, 210, 120, 255))
        points = data["joints"]
        for a, b in (("head", "upper_arm_left"), ("head", "upper_arm_right"), ("upper_arm_left", "upper_leg_left"), ("upper_arm_right", "upper_leg_right"), ("upper_leg_left", "foot_left"), ("upper_leg_right", "foot_right")):
            draw.line((*points[a], *points[b]), fill=(90, 255, 190, 210), width=2)
        for name, point in points.items():
            x, y = point; draw.ellipse((x-4, y-4, x+4, y+4), fill=colors[name], outline=(0, 0, 0, 255))
            if previous and name in previous:
                px, py = previous[name]
                if abs(x-px)+abs(y-py) > 1: draw.line((px, py, x, y), fill=(255, 245, 110, 220), width=2)
        previous = points
        image.save(debug_dir / f"frame_{frame:04d}.jpg", quality=90)
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i", str(debug_dir / "frame_%04d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "21", str(output_path)], check=True)
    return output_path


def _distance(a, b):
    return math.sqrt(sum((float(x)-float(y))**2 for x, y in zip(a, b)))


def _joint_motion(telemetry, start, end):
    values = []
    keys = ("upper_arm_left", "upper_arm_right", "upper_leg_left", "upper_leg_right", "foot_left", "foot_right", "head")
    for frame in range(start+1, end+1):
        before, after = telemetry[frame-1]["joints"], telemetry[frame]["joints"]
        # Subtract head displacement so a rigid translated PNG scores near zero.
        root_dx = after["head"][0] - before["head"][0]
        root_dy = after["head"][1] - before["head"][1]
        for key in keys[1:]:
            dx = after[key][0]-before[key][0]-root_dx; dy = after[key][1]-before[key][1]-root_dy
            values.append(math.hypot(dx, dy))
    return sum(values) / max(1, len(values))
