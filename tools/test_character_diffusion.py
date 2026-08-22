"""Isolated DreamShaper/ComfyUI proof: one PNG, no Blender or renderer."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.characters.errors import CharacterGenerationError, DIFFUSION_FAILURE
from app.characters.quality import inspect_diffusion_master
from app.image_generation.comfyui_client import ComfyUIClient


MODEL = Path(r"D:\AI_VIDEO_GENERATOR\models\checkpoints\DreamShaper_8_pruned.safetensors")
WORKFLOW = ROOT / "workflows" / "character_master.json"
OUTPUT_DIR = ROOT / "output" / "character_generation_test"
OUTPUT = OUTPUT_DIR / "arun_diffusion_test.png"
PROMPT = (
    "full body cinematic 2D illustrated documentary character, adult Indian man, approximately 35 years old, "
    "medium build, natural human anatomy, realistic hands and feet, expressive but restrained face, short dark hair, "
    "wearing a historically appropriate 1980s Bengaluru bank employee outfit, shirt and trousers, leather shoes, "
    "standing upright, full body visible from head to feet, three-quarter view, professional digital illustration, "
    "painterly texture, cinematic lighting, natural proportions, detailed face, detailed clothing, subtle skin texture, "
    "clean silhouette, isolated character, neutral background"
)
NEGATIVE = (
    "stick figure, primitive character, geometric human, vector mascot, SVG, flat icon, simple cartoon, chibi, "
    "capsule body, cylindrical arms, cylindrical legs, sphere head, rectangle torso, malformed anatomy, extra limbs, "
    "extra fingers, missing fingers, distorted face, deformed hands, bad feet, cropped body, low detail, blurry, low resolution"
)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> int:
    base_url = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise CharacterGenerationError(DIFFUSION_FAILURE + " ComfyUI must be localhost-only.")
    if not MODEL.is_file() or MODEL.stat().st_size != 2_132_625_894:
        raise CharacterGenerationError(DIFFUSION_FAILURE + f" Expected checkpoint missing or changed: {MODEL}")
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    checkpoint = workflow.get("4", {}).get("inputs", {}).get("ckpt_name")
    if checkpoint != MODEL.name:
        raise CharacterGenerationError(DIFFUSION_FAILURE + " Workflow does not select DreamShaper 8.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bible = {
        "character_id": "arun_bank_employee_1985", "name": "Arun", "fictional": True,
        "age": 35, "heritage": "Indian", "era": "1980s Bengaluru",
        "canonical_source": str(OUTPUT), "source_type": "local_diffusion_png",
        "production_approved": False,
    }
    config = {
        "provider": "ComfyUI localhost", "backend_url": base_url,
        "model": MODEL.name, "model_path": str(MODEL), "model_bytes": MODEL.stat().st_size,
        "model_sha256": "879db523c30d3b9017143d56705015e15a2cb5628762c11d086fed9538abd7fd",
        "license": "CreativeML OpenRAIL-M restrictions apply; no unrestricted-commercial-use claim",
        "workflow": str(WORKFLOW), "width": 512, "height": 768, "steps": 12,
        "cfg": 6.5, "sampler": "dpmpp_2m", "scheduler": "karras",
        "seed": 19850317, "denoise": 1.0, "prompt": PROMPT, "negative_prompt": NEGATIVE,
        "primitive_fallback": False, "blender_involved": False, "renderer_involved": False,
        "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _write(OUTPUT_DIR / "character_bible.json", bible)
    _write(OUTPUT_DIR / "generation_manifest.json", config)

    peak = {"used": psutil.virtual_memory().used}
    stop = threading.Event()
    def sample_memory() -> None:
        while not stop.wait(.25):
            peak["used"] = max(peak["used"], psutil.virtual_memory().used)
    sampler = threading.Thread(target=sample_memory, daemon=True); sampler.start()
    started = time.perf_counter()
    try:
        client = ComfyUIClient(base_url, timeout=1800)
        health = client.health()
        result = client.generate(
            WORKFLOW, PROMPT, OUTPUT, negative_prompt=NEGATIVE,
            width=512, height=768, steps=12, cfg=6.5, seed=19850317, denoise=1.0,
        )
        if result.resolve() != OUTPUT.resolve():
            raise RuntimeError("ComfyUI result was not saved to the required path")
    except Exception as exc:
        OUTPUT.unlink(missing_ok=True)
        config.update({"status": "failed", "error": str(exc)[:1200]})
        _write(OUTPUT_DIR / "generation_manifest.json", config)
        raise CharacterGenerationError(DIFFUSION_FAILURE) from exc
    finally:
        stop.set(); sampler.join(timeout=1)

    seconds = round(time.perf_counter() - started, 3)
    report = inspect_diffusion_master(OUTPUT)
    report.update({
        "source": str(OUTPUT), "source_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        "generation_seconds": seconds, "system_ram_peak_gb": round(peak["used"] / 1024**3, 2),
        "comfyui_system": health.get("system", {}),
    })
    config.update({"status": "generated_manual_review_required", "completed_at": datetime.now(timezone.utc).isoformat(), "generation_seconds": seconds})
    _write(OUTPUT_DIR / "generation_manifest.json", config)
    _write(OUTPUT_DIR / "quality_report.json", report)
    print(json.dumps({"status": config["status"], "output": str(OUTPUT), "quality": report}, indent=2))
    return 0 if report["technical_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
