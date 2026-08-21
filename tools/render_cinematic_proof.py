"""Render a short, original cinematic-documentary pipeline proof.

This intentionally uses a fictional case so the style can be evaluated without
copying the people, claims, artwork, or branding of any reference video.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agents.asset_agent import AssetAgent
from app.agents.base import AgentContext
from app.agents.music_agent import MusicAgent
from app.agents.video_edit_agent import VideoEditAgent, _probe_duration
from app.agents.voice_agent import VoiceAgent


OUTPUT_DIR = Path("output/cinematic_style_test")


SCENES = [
    {
        "scene_id": 1,
        "duration_seconds": 5.0,
        "narration": "At two seventeen, the last signal left Blackridge Tower.",
        "visual_description": "A lonely radio tower above a forest during a storm.",
        "image_prompt": (
            "fictional Blackridge radio tower at night, heavy monsoon clouds, one red "
            "warning lamp, wet pine forest, distant amber town lights, ominous wide shot"
        ),
        "animation_type": "zoom-in",
        "text_overlay": "02:17 AM",
        "overlay_style": "date",
        "transition": "fade",
        "music_mood": "mysterious",
        "sfx": ["wind"],
        "asset_type": "cinematic-reenactment",
        "character_name": "Maya Rao",
        "character_action": "enters the tower clearing and studies the warning light",
        "character_motion": "walk-in-right",
        "character_position": "right",
        "character_scale": 0.62,
        "character_is_fictional": True,
    },
    {
        "scene_id": 2,
        "duration_seconds": 5.0,
        "narration": "Its final transmission contained one impossible coordinate.",
        "visual_description": "A dark relief map with a route ending outside the valley.",
        "image_prompt": (
            "fictional mountain valley topographic map seen from above, a single glowing "
            "amber signal route ending at an isolated crimson point beyond the ridge"
        ),
        "animation_type": "pan-right",
        "text_overlay": "BLACKRIDGE VALLEY",
        "overlay_style": "location",
        "transition": "wipe-right",
        "music_mood": "tense",
        "sfx": ["whoosh"],
        "asset_type": "animated-map",
    },
    {
        "scene_id": 3,
        "duration_seconds": 5.0,
        "narration": "The official log said the station had been empty.",
        "visual_description": "A weathered station log photographed on an evidence desk.",
        "image_prompt": (
            "weathered fictional radio station logbook on a dark evidence table, empty "
            "entry line circled in amber grease pencil, flashlight beam, paper fibers"
        ),
        "animation_type": "ken-burns",
        "text_overlay": "THE LOGBOOK",
        "overlay_style": "evidence",
        "transition": "dissolve",
        "music_mood": "tense",
        "sfx": ["chime"],
        "asset_type": "newspaper-document",
        "character_name": "Maya Rao",
        "character_action": "stands beside the evidence and pauses to think",
        "character_motion": "idle-breathe",
        "character_position": "left",
        "character_scale": 0.50,
        "character_is_fictional": True,
    },
    {
        "scene_id": 4,
        "duration_seconds": 5.0,
        "narration": "But a photograph showed someone entering twelve minutes earlier.",
        "visual_description": "An evidence board connecting a tower photograph to a clock.",
        "image_prompt": (
            "investigative evidence board for a fictional mystery, one surveillance photo "
            "of a hooded silhouette approaching a radio tower, clock photo, red thread"
        ),
        "animation_type": "pan-left",
        "text_overlay": "ONE FRAME SURVIVED",
        "overlay_style": "headline",
        "transition": "zoom-through",
        "music_mood": "dramatic",
        "sfx": ["whoosh"],
        "asset_type": "evidence-board",
    },
    {
        "scene_id": 5,
        "duration_seconds": 5.0,
        "narration": "And the person in that frame was never identified.",
        "visual_description": "A silhouette in rain beneath the tower's warning lamp.",
        "image_prompt": (
            "anonymous adult silhouette in a raincoat beneath a radio tower, viewed from "
            "behind, red warning lamp through fog, amber rim light, tense final reveal"
        ),
        "animation_type": "zoom-out",
        "text_overlay": "THE VANISHING SIGNAL",
        "overlay_style": "headline",
        "transition": "fade",
        "music_mood": "dramatic",
        "sfx": ["ambient-space"],
        "asset_type": "cinematic-reenactment",
        "character_name": "Maya Rao",
        "character_action": "emerges from fog for the final reveal",
        "character_motion": "reveal",
        "character_position": "left",
        "character_scale": 0.64,
        "character_is_fictional": True,
    },
]


def _run(agent, context: AgentContext):
    result = agent.run(context)
    if not result.success:
        raise RuntimeError(f"{result.agent_name} failed: {result.error}")
    return result.output


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    context = AgentContext(
        project_id="cinematic_style_test",
        topic="The Vanishing Signal (fictional style proof)",
        chosen_topic="The Vanishing Signal (fictional style proof)",
        style="premium cinematic documentary",
        target_duration_seconds=25,
        output_dir=OUTPUT_DIR,
        storyboard=SCENES,
    )
    context.character_sheet = {
        "characters": [
            {
                "name": "Maya Rao",
                "role": "investigator and visual guide",
                "visual": (
                    "Original Indian woman in her early thirties, medium build, warm brown "
                    "skin, dark swept hair, forest-green field coat with one amber seam, "
                    "charcoal trousers, calm observant expression"
                ),
            }
        ],
        "settings": [],
    }

    context.images = _run(AssetAgent(), context)
    context.narration_files = _run(VoiceAgent(), context)
    context.music_path = _run(MusicAgent(), context)
    context.video_path = _run(VideoEditAgent(), context)

    result = {
        "video": str(context.video_path.resolve()),
        "duration_seconds": round(_probe_duration(context.video_path), 2),
        "size_bytes": context.video_path.stat().st_size,
        "scenes": len(SCENES),
        "images": len(context.images),
        "narration_tracks": len(context.narration_files),
    }
    (OUTPUT_DIR / "proof_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
