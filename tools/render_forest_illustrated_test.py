"""Render the production-quality illustrated Forest Encounter acceptance test."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import settings  # noqa: E402
from app.images.production_assets import (  # noqa: E402
    ArtDirection,
    prepare_production_assets,
)
from app.video.animated_renderer import Cinematic2DRenderer  # noqa: E402
from app.video.timeline import build_production_scene  # noqa: E402

OUTPUT_DIR = Path("output/forest_illustrated_test")
SOURCE_DIR = Path("assets/production/forest_encounter")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    assets = prepare_production_assets(
        SOURCE_DIR / "environment" / "forest_master.png",
        SOURCE_DIR / "characters" / "ravi" / "reference.png",
        SOURCE_DIR / "characters" / "ravi" / "expressions" / "fear.png",
        OUTPUT_DIR / "assets",
        ArtDirection(),
    )
    audio_path = _create_soundscape(OUTPUT_DIR / "forest_soundscape.wav")
    scene = build_production_scene({
        "scene_id": 1,
        "title": "Forest Encounter",
        "duration_seconds": 10.0,
        "narration": "",
        "visual_description": "A young man walks alone through a mysterious illustrated forest at night.",
        "image_prompt": "Production illustrated moonlit forest plate with organic detail and layered depth",
        "character_name": "Ravi",
        "character_action": "walk",
        "character_motion": "walk-across",
        "character_is_fictional": True,
        "music_mood": "tense",
        "voice_emotion": "tense",
        "sfx": ["footsteps", "wind"],
        "render_quality": "FINAL",
        "visual_quality": "PRODUCTION",
        "environment_assets": assets["environment"]["layers"],
        "character_asset": assets["character"]["reference"],
        "character_rig_manifest": assets["character"]["rig_manifest"],
        "character_expressions": assets["character"]["expressions"],
        "art_direction": assets["art_direction"],
        "asset_quality": assets["quality_reports"],
        "shots": [
            {
                "duration": 2.5, "shot_type": "wide",
                "camera": {"move": "slow_push", "easing": "ease_in_out"},
                "action": "walk", "expression": "neutral", "transition": "cut",
            },
            {
                "duration": 2.5, "shot_type": "medium",
                "camera": {"move": "track_character", "easing": "ease_in_out"},
                "action": "walk", "expression": "confused", "transition": "cut",
            },
            {
                "duration": 2.5, "shot_type": "medium",
                "camera": {"move": "dolly_in", "easing": "ease_in_out"},
                "action": "turn_head", "expression": "confused", "transition": "crossfade",
            },
            {
                "duration": 2.5, "shot_type": "closeup",
                "camera": {"move": "orbit_simulation", "easing": "ease_in_out"},
                "action": "react", "expression": "fear", "transition": "cut",
            },
        ],
    })
    plan_path = OUTPUT_DIR / "production_plan.json"
    plan_path.write_text(json.dumps({
        "production_version": 1,
        "title": "Forest Encounter",
        "assets": assets,
        "scenes": [scene],
    }, indent=2), encoding="utf-8")

    video_path = OUTPUT_DIR / "forest_illustrated_test.mp4"
    Cinematic2DRenderer(
        settings.video_width, settings.video_height, settings.video_fps
    ).render_scene(
        scene,
        Path(assets["environment"]["master"]),
        video_path,
        narration_path=audio_path,
        quality="FINAL",
    )
    contact_sheet = _contact_sheet(
        video_path,
        Path(assets["character"]["reference"]),
        Path(assets["environment"]["master"]),
        OUTPUT_DIR / "contact_sheet.jpg",
    )
    print(json.dumps({
        "video": str(video_path.resolve()),
        "contact_sheet": str(contact_sheet.resolve()),
        "production_plan": str(plan_path.resolve()),
        "asset_manifest": assets["manifest_path"],
        "duration_seconds": 10.0,
        "shots": 4,
        "animation_quality": scene["animation_quality"],
        "asset_quality": [
            {"type": item["asset_type"], "score": item["score"], "passed": item["passed"]}
            for item in assets["quality_reports"]
        ],
    }, indent=2))


def _create_soundscape(path: Path) -> Path:
    command = [
        settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "anoisesrc=color=pink:duration=10,lowpass=f=850,volume=0.025",
        "-f", "lavfi", "-i",
        r"aevalsrc='if(lt(mod(t\,0.62)\,0.075)\,0.72*sin(2*PI*(78+22*exp(-mod(t\,0.62)*18))*t)*exp(-mod(t\,0.62)*34)\,0)':s=48000:d=7.35,lowpass=f=430,volume=0.38",
        "-f", "lavfi", "-i", "sine=frequency=318:duration=0.32,afade=t=out:st=0.04:d=0.28,volume=0.09",
        "-filter_complex", "[2:a]adelay=8500|8500[behind];[0:a][1:a][behind]amix=inputs=3:duration=longest:normalize=0,alimiter=limit=0.72[aout]",
        "-map", "[aout]", "-ar", "48000", "-t", "10", str(path),
    ]
    subprocess.run(command, check=True)
    return path


def _contact_sheet(video: Path, character: Path, environment: Path, output: Path) -> Path:
    frames_dir = output.parent / "contact_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    times = (1.1, 3.7, 6.2, 8.6)
    frames = []
    for index, timestamp in enumerate(times, 1):
        path = frames_dir / f"shot_{index}.jpg"
        subprocess.run([
            settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(timestamp), "-i", str(video), "-frames:v", "1", str(path),
        ], check=True)
        frames.append(path)

    cell_w, cell_h, label_h = 640, 360, 38
    sheet = Image.new("RGB", (cell_w * 3, (cell_h + label_h) * 2), (7, 13, 17))
    font = _font(25)
    entries = [(character, "CHARACTER REFERENCE"), (environment, "ILLUSTRATED ENVIRONMENT")]
    entries.extend((path, f"SHOT {index}") for index, path in enumerate(frames, 1))
    draw = ImageDraw.Draw(sheet)
    for index, (path, label) in enumerate(entries):
        source = Image.open(path).convert("RGBA")
        background = Image.new("RGBA", (cell_w, cell_h), (10, 18, 22, 255))
        fitted = ImageOps.contain(source, (cell_w, cell_h), Image.Resampling.LANCZOS)
        background.alpha_composite(fitted, ((cell_w - fitted.width) // 2, (cell_h - fitted.height) // 2))
        x = (index % 3) * cell_w
        y = (index // 3) * (cell_h + label_h)
        sheet.paste(background.convert("RGB"), (x, y))
        draw.rectangle((x, y + cell_h, x + cell_w, y + cell_h + label_h), fill=(4, 9, 13))
        draw.text((x + 16, y + cell_h + 6), label, font=font, fill=(221, 229, 224))
    sheet.save(output, "JPEG", quality=94, subsampling=0)
    return output


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


if __name__ == "__main__":
    main()
