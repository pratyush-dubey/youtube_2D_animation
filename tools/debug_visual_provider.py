"""TEST 2: ComfyUICharacterProvider -> ComfyUI -> one validated PNG."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.characters.provider import ComfyUICharacterProvider
from app.config.settings import settings
from app.image_generation.visual_stage import validate_image
from tools._visual_debug_common import OUTPUT, SHOT, record

PROMPT = "fictional adult Indian man walking, 1980s Bengaluru clothing, full body, natural anatomy, cinematic 2D illustrated documentary character, no text"


def main() -> int:
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        provider = ComfyUICharacterProvider(settings.comfyui_base_url)
        if not provider.configured:
            raise RuntimeError("ComfyUICharacterProvider is not configured")
        provider.generate_master_character(PROMPT, SHOT)
        result = validate_image(SHOT, 512, 768)
        record("provider", "PASS", provider=provider.name, output=str(SHOT.resolve()), prompt_id=provider.client.last_generation.get("prompt_id"), validation=result)
        print(f"PASS: {SHOT}")
        return 0
    except Exception as exc:
        record("provider", "FAIL", error=exc)
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

