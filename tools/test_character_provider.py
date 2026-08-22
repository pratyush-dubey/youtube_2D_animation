"""Exercise CharacterImageProvider -> ComfyUIProvider -> ComfyUI -> PNG."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.characters.provider import ComfyUICharacterProvider

OUTPUT = ROOT / "output" / "character_generation_test" / "provider_test.png"
PROMPT = (
    "cinematic 2D illustrated documentary character, adult Indian man, 28 years old, South Indian appearance, "
    "warm brown skin, natural human anatomy, realistic face, short black hair, neatly groomed short beard, "
    "olive green linen shirt, dark charcoal trousers, brown leather shoes, full body, standing, three-quarter view, "
    "professional digital illustration, painterly texture, cinematic lighting, detailed clothing, natural proportions, clean silhouette"
)


def main() -> int:
    provider = ComfyUICharacterProvider("http://127.0.0.1:8188")
    if not provider.configured:
        raise RuntimeError("ComfyUICharacterProvider is not configured")
    started = time.perf_counter()
    result = provider.generate_master_character(PROMPT, OUTPUT)
    elapsed = round(time.perf_counter() - started, 3)
    print(json.dumps({"status": "PASS", "provider": provider.name, "model": provider.model, "output": str(result), "generation_time": elapsed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
