"""TEST 1: bypass Director/provider/DB/queue and generate exactly one PNG."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import settings
from app.image_generation.comfyui_client import ComfyUIClient
from app.image_generation.visual_stage import validate_image
from tools._visual_debug_common import OUTPUT, SHOT, record

PROMPT = "1980s Bengaluru street, fictional adult Indian man walking, period-appropriate street, early morning, cinematic illustrated documentary, natural anatomy, no text"
NEGATIVE = "text, watermark, modern cars, malformed anatomy, extra limbs, blank, solid color, transparent"


def main() -> int:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        client = ComfyUIClient(
            settings.comfyui_base_url,
            timeout=settings.comfyui_generation_timeout_seconds,
            connect_timeout=settings.comfyui_connect_timeout_seconds,
            poll_interval=settings.comfyui_poll_interval_seconds,
        )
        health = client.health()
        client.validate_checkpoint("DreamShaper_8_pruned.safetensors")
        client.generate(
            settings.comfyui_scene_workflow, PROMPT, SHOT,
            negative_prompt=NEGATIVE, width=512, height=768, steps=8,
            cfg=6.5, seed=19850318, denoise=1.0,
        )
        result = validate_image(SHOT, 512, 768)
        record("direct_comfyui", "PASS", output=str(SHOT.resolve()), prompt_id=client.last_generation.get("prompt_id"), system=health.get("system", {}), validation=result)
        print(f"PASS: {SHOT}")
        return 0
    except Exception as exc:
        record("direct_comfyui", "FAIL", error=exc)
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
