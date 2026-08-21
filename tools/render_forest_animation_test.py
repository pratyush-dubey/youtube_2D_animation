"""Render the required 10-second cinematic forest acceptance scene."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import settings
from app.video.animated_renderer import Cinematic2DRenderer
from app.video.timeline import build_production_scene


OUTPUT_DIR = Path("output/forest_animation_test")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scene = build_production_scene({
        "scene_id": 1,
        "duration_seconds": 10.0,
        "narration": "A man walks through a dark forest at night. He stops when footsteps behind him suddenly fall silent.",
        "visual_description": "A moonlit pine forest at night with dense moving fog and cold light rays.",
        "image_prompt": "Layered original 2D moonlit forest environment plate, no people, deep foreground and distant trees",
        "character_name": "Ravi",
        "character_action": "walk",
        "character_motion": "walk-across",
        "character_is_fictional": True,
        "music_mood": "tense",
        "voice_emotion": "tense",
        "sfx": ["footsteps"],
        "render_quality": "FINAL",
        "shots": [
            {
                "id": "1A", "duration": 2.0, "shot_type": "wide",
                "camera": {"move": "slow_push"}, "action": "walk", "expression": "neutral",
            },
            {
                "id": "1B", "duration": 3.0, "shot_type": "medium",
                "camera": {"move": "track_character"}, "action": "walk", "expression": "confused",
            },
            {
                "id": "1C", "duration": 2.0, "shot_type": "medium",
                "camera": {"move": "dolly_in"}, "action": "turn_head", "expression": "fear",
            },
            {
                "id": "1D", "duration": 2.0, "shot_type": "closeup",
                "camera": {"move": "handheld"}, "action": "react", "expression": "surprised",
            },
            {
                "id": "1E", "duration": 1.0, "shot_type": "rear",
                "camera": {"move": "orbit_simulation"}, "action": "stop", "expression": "fear",
            },
        ],
    })
    # The acceptance scene needs footsteps that stop before the rear shot.
    sfx_path = OUTPUT_DIR / "footsteps.wav"
    if not sfx_path.exists():
        subprocess.run([
            settings.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            "aevalsrc='if(lt(mod(t\\,0.62)\\,0.075)\\,0.72*sin(2*PI*(78+22*exp(-mod(t\\,0.62)*18))*t)*exp(-mod(t\\,0.62)*34)\\,0)':s=48000:d=6.75,lowpass=f=430,volume=0.42",
            str(sfx_path),
        ], check=True)

    plan_path = OUTPUT_DIR / "production_plan.json"
    plan_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    video_path = OUTPUT_DIR / "forest_10s.mp4"
    Cinematic2DRenderer(
        settings.video_width, settings.video_height, settings.video_fps
    ).render_scene(scene, None, video_path, sfx_path=sfx_path, quality="FINAL")
    print(json.dumps({
        "video": str(video_path.resolve()),
        "plan": str(plan_path.resolve()),
        "duration_seconds": 10.0,
        "shots": len(scene["shots"]),
        "animation_quality": scene["animation_quality"],
    }, indent=2))


if __name__ == "__main__":
    main()
