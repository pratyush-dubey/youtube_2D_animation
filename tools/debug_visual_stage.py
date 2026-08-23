"""TEST 3: actual VisualDirector -> one cached-planned shot -> one real image."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image

from app.agents.base import AgentContext
from app.director.director import VisualDirector
from app.image_generation.visual_stage import validate_image
from app.script.schemas import ScriptResult, ScriptSection
from tools._visual_debug_common import OUTPUT, SHOT, record


class NoLLM:
    """The exact one-scene plan is cached, so any LLM call is a test failure."""
    provider_name = "disabled_for_forensic_test"
    def generate_json(self, *args, **kwargs):
        raise RuntimeError("VisualDirector unexpectedly called the LLM despite cached one-scene plan")


def main() -> int:
    project_id = "debug_visual_test"
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for stale in (
            OUTPUT / "images" / "scene_001.jpg",
            OUTPUT / "images" / "manifest.json",
            OUTPUT / "visual_manifest.json",
        ):
            stale.unlink(missing_ok=True)
        script = ScriptResult(
            title="Muthappa Rai visual connectivity test", hook="A period street scene.",
            sections=[ScriptSection(id=1, title="Visual test", narration="A fictional man walks through a Bengaluru street.", duration_seconds=10)],
            estimated_duration_seconds=10,
        )
        scene = {
            "scene_id": 1, "duration_seconds": 10,
            "narration": "A fictional adult Indian man walks through a period-appropriate Bengaluru street.",
            "visual_description": "1980s Bengaluru street in the early morning",
            "image_prompt": "1980s Bengaluru street, fictional adult Indian man walking, period-appropriate buildings and clothing, early morning, cinematic illustrated documentary, natural anatomy, no text",
            "animation_type": "pan-right", "camera_motion": "slow pan right",
            "asset_type": "cinematic-reenactment", "visual_quality": "DEBUG",
            "shots": [{"id": "shot_001", "shot_type": "wide", "action": "fictional adult Indian man walks", "lighting": "early morning"}],
        }
        (OUTPUT / "storyboard.json").write_text(json.dumps({"total_scenes": 1, "total_duration_seconds": 10, "scenes": [scene]}, indent=2), encoding="utf-8")
        context = AgentContext(
            project_id=project_id, topic="Muthappa Rai", target_duration_seconds=10,
            output_dir=OUTPUT, script=script,
            character_sheet={"characters": [], "settings": []},
        )
        result = VisualDirector(NoLLM()).run(context)
        source = Path(result[1])
        with Image.open(source) as image:
            image.save(SHOT, "PNG")
        validation = validate_image(SHOT, 768, 432)
        record("visual_director", "PASS", output=str(SHOT.resolve()), source=str(source.resolve()), validation=validation)
        print(f"PASS: {SHOT}")
        return 0
    except Exception as exc:
        record("visual_director", "FAIL", error=exc)
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
