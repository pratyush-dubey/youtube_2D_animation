"""Generate exactly one diagnostic PNG directly through localhost ComfyUI."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.image_generation.comfyui_client import ComfyUIClient

OUTPUT_DIR = ROOT / "output" / "character_generation_test"
OUTPUT = OUTPUT_DIR / "comfyui_direct_test.png"
METADATA = OUTPUT_DIR / "comfyui_direct_test_metadata.json"
WORKFLOW = ROOT / "workflows" / "character_master.json"
MODEL = "DreamShaper_8_pruned.safetensors"
PROMPT = (
    "cinematic 2D illustrated documentary character, adult Indian man, 28 years old, South Indian appearance, "
    "warm brown skin, natural human anatomy, realistic face, short black hair, neatly groomed short beard, "
    "olive green linen shirt, dark charcoal trousers, brown leather shoes, full body, standing, three-quarter view, "
    "professional digital illustration, painterly texture, cinematic lighting, detailed clothing, natural proportions, clean silhouette"
)
NEGATIVE = (
    "stick figure, geometric human, primitive character, SVG, vector mascot, simple cartoon, chibi, sphere head, "
    "rectangle torso, capsule limbs, malformed anatomy, extra limbs, bad hands, bad feet, distorted face, blurry, low quality"
)


def main() -> int:
    base_url = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    timeout = int(os.getenv("COMFYUI_GENERATION_TIMEOUT_SECONDS", os.getenv("COMFYUI_TIMEOUT_SECONDS", "1800")))
    client = ComfyUIClient(base_url, timeout=timeout)
    health = client.health()
    object_info = client._json("GET", "/object_info/CheckpointLoaderSimple")
    checkpoints = object_info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    if MODEL not in checkpoints:
        raise RuntimeError(f"Checkpoint not visible in ComfyUI: {MODEL}; visible={checkpoints}")

    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    sampler = workflow["3"]["inputs"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result = client.generate(
        WORKFLOW,
        PROMPT,
        OUTPUT,
        negative_prompt=NEGATIVE,
        width=512,
        height=768,
        steps=12,
        cfg=6.5,
        seed=19850317,
        denoise=1.0,
    )
    elapsed = round(time.perf_counter() - started, 3)
    metadata = {
        "model": MODEL,
        "seed": 19850317,
        "width": 512,
        "height": 768,
        "steps": 12,
        "sampler": sampler["sampler_name"],
        "scheduler": sampler["scheduler"],
        "generation_time": elapsed,
        "provider": "comfyui_local",
        "comfyui_url": base_url,
        "prompt_id": client.last_generation.get("prompt_id"),
        "prompt": PROMPT,
        "negative_prompt": NEGATIVE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workflow": client.last_generation.get("workflow", workflow),
        "comfyui_system": health.get("system", {}),
        "output": str(result.resolve()),
    }
    METADATA.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(result), "metadata": str(METADATA), "generation_time": elapsed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
