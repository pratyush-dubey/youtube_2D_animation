"""Run and record the required ComfyUI resolution benchmark."""
from __future__ import annotations

import json
import os
import sys
import time
import threading
import argparse
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from app.image_generation.comfyui_client import ComfyUIClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="ComfyUI")
    parser.add_argument("--report", type=Path, default=Path("image_generation_benchmark.json"))
    args = parser.parse_args()
    client = ComfyUIClient(os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188"), timeout=1800)
    workflow = ROOT / "workflows" / "character_master.json"
    out = Path(r"D:\AI_VIDEO_GENERATOR\output\benchmark")
    prompt = "cinematic illustrated documentary portrait of a fictional 35-year-old Indian bank employee in 1985 Bengaluru, natural anatomy, painterly texture"
    negative = "deformed, extra fingers, extra limbs, text, watermark, 3d render"
    results = []
    for size in (512, 768, 1024):
        start_memory = psutil.virtual_memory().used
        peak = {"used": start_memory}; stop_sample = threading.Event()
        def sample_memory():
            while not stop_sample.wait(.25): peak["used"] = max(peak["used"], psutil.virtual_memory().used)
        sampler = threading.Thread(target=sample_memory, daemon=True); sampler.start()
        started = time.perf_counter()
        record = {"width": size, "height": size, "success": False}
        try:
            path = client.generate(workflow, prompt, out / f"benchmark_{size}.png", negative_prompt=negative, width=size, height=size, steps=12, seed=19850317)
            record.update({"success": True, "output": str(path)})
        except Exception as exc:
            record["error"] = str(exc)
        stop_sample.set(); sampler.join(timeout=1)
        record["generation_seconds"] = round(time.perf_counter() - started, 3)
        record["system_ram_delta_mb"] = round((psutil.virtual_memory().used - start_memory) / 1024**2, 1)
        record["system_ram_peak_gb"] = round(peak["used"] / 1024**3, 2)
        record["system_ram_used_gb_after"] = round(psutil.virtual_memory().used / 1024**3, 2)
        record["dedicated_vram_mb"] = 128
        record["vram_usage_measurement"] = "unavailable for this Intel UHD/DirectML backend"
        results.append(record)
        if size == 512 and (not record["success"] or record["generation_seconds"] > 1800):
            for skipped in (768, 1024):
                results.append({"width": skipped, "height": skipped, "success": False, "skipped": True, "reason": "512px failed or exceeded the 30-minute usability ceiling"})
            break
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "backend": args.backend, "results": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)); return 0 if results[0]["success"] else 2


if __name__ == "__main__": raise SystemExit(main())
