"""Isolated SCRIPT -> visual plan -> one ComfyUI image diagnostic.

This command intentionally does not invoke audio, animation, rendering,
subtitles, thumbnails, uploads, or the full Director production graph.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import settings
from app.image_generation.comfyui_client import ComfyUIClient
from app.image_generation.visual_stage import VisualStageLog, utc_now, validate_image, write_failure_report

MODEL = "DreamShaper_8_pruned.safetensors"
WIDTH, HEIGHT = 512, 768
SEED, STEPS, CFG = 19850318, 8, 6.5
SCENE_ID, SHOT_ID = "scene_001", "shot_001"
PROMPT = (
    "1980s Bengaluru street in India in the early morning, an adult Indian man "
    "walking naturally along the street, period-correct shopfronts, old Bengaluru "
    "architecture, sparse traffic, soft dawn haze, warm directional sunlight, full-body "
    "wide shot, eye-level camera, balanced cinematic composition, professional painterly "
    "2D illustrated documentary frame, detailed environment, natural anatomy"
)
NEGATIVE = (
    "text, watermark, logo, modern skyscrapers, modern cars, child, malformed anatomy, "
    "extra limbs, duplicate people, primitive character, stick figure, solid color, blank, "
    "transparent, blurry, low detail"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(settings.output_dir) / args.project_id
    debug_dir = output_dir / "visual_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    output = debug_dir / "visual_test_001.png"
    metadata_path = debug_dir / "visual_test_001.json"
    manifest_path = output_dir / "visual_manifest.json"
    workflow_path = Path(settings.comfyui_scene_workflow)
    audit = VisualStageLog(output_dir, args.project_id)
    started = time.perf_counter()
    prompt_id = None
    diagnostic = {
        "comfyui": "FAIL", "checkpoint": "FAIL", "workflow": "FAIL",
        "prompt_submission": "FAIL", "prompt_id": "FAIL", "generation": "FAIL",
        "image_retrieval": "FAIL", "image_validation": "FAIL", "visual_manifest": "FAIL",
        "background_worker": "NOT_TESTED", "browser_progress": "NOT_TESTED",
    }
    manifest = {
        "project_id": args.project_id,
        "provider": "comfyui_local",
        "reference_conditioning": False,
        "architecture": "complete_scene_diffusion_for_isolated_diagnostic",
        "scenes": [{
            "scene_id": SCENE_ID,
            "shots": [{
                "shot_id": SHOT_ID,
                "environment": "1980s Bengaluru street in the early morning",
                "characters": ["adult_indian_man"],
                "camera": "eye-level wide shot",
                "lighting": "soft warm early-morning directional light",
                "composition": "full-body subject walking through a period street",
                "action": "An adult Indian man walks along a Bengaluru street",
                "image_status": "pending",
                "image_path": None,
            }],
        }],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    audit.emit("VISUALS_STARTED")
    audit.emit("VISUALS_SCRIPT_PARSED", scene_id=SCENE_ID)
    audit.emit("VISUAL_SCENES_PLANNED", scene_id=SCENE_ID, shot_id=SHOT_ID, scene_count=1)
    audit.emit("VISUAL_PROMPTS_CREATED", scene_id=SCENE_ID, shot_id=SHOT_ID)

    try:
        client = ComfyUIClient(
            settings.comfyui_base_url,
            timeout=settings.comfyui_generation_timeout_seconds,
            connect_timeout=settings.comfyui_connect_timeout_seconds,
            poll_interval=settings.comfyui_poll_interval_seconds,
        )
        health = client.health()
        diagnostic["comfyui"] = "PASS"
        client.validate_checkpoint(MODEL)
        diagnostic["checkpoint"] = "PASS"
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        nodes = client.validate_workflow(workflow)
        diagnostic["workflow"] = "PASS"
        audit.emit("VISUAL_GENERATION_STARTED", scene_id=SCENE_ID, shot_id=SHOT_ID)

        def progress(event: str, details: dict) -> None:
            nonlocal prompt_id
            if event == "submitting":
                diagnostic["prompt_submission"] = "PASS"
                audit.emit("COMFYUI_REQUEST_SENT", scene_id=SCENE_ID, shot_id=SHOT_ID, **details)
            elif event == "generating":
                prompt_id = details.get("prompt_id")
                diagnostic["prompt_id"] = "PASS" if prompt_id else "FAIL"
                audit.emit("COMFYUI_PROMPT_ID_RECEIVED", scene_id=SCENE_ID, shot_id=SHOT_ID, **details)
                audit.emit("COMFYUI_GENERATION_STARTED", scene_id=SCENE_ID, shot_id=SHOT_ID, **details)
            elif event == "retrieving":
                diagnostic["generation"] = "PASS"
                audit.emit("COMFYUI_GENERATION_COMPLETED", scene_id=SCENE_ID, shot_id=SHOT_ID, **details)
            elif event == "saved":
                diagnostic["image_retrieval"] = "PASS"
                audit.emit("IMAGE_RETRIEVED", scene_id=SCENE_ID, shot_id=SHOT_ID, **details)

        client.generate(
            workflow_path, PROMPT, output, negative_prompt=NEGATIVE,
            width=WIDTH, height=HEIGHT, steps=STEPS, cfg=CFG, seed=SEED,
            denoise=1.0, progress_callback=progress,
        )
        validation = validate_image(output, WIDTH, HEIGHT)
        diagnostic["image_validation"] = "PASS"
        audit.emit("IMAGE_VALIDATED", scene_id=SCENE_ID, shot_id=SHOT_ID, **validation)
        audit.emit("VISUAL_ASSET_SAVED", scene_id=SCENE_ID, shot_id=SHOT_ID, path=str(output.resolve()))
        generation_time = round(time.perf_counter() - started, 3)
        metadata = {
            "model": MODEL, "seed": SEED, "width": WIDTH, "height": HEIGHT,
            "steps": STEPS,
            "sampler": workflow[nodes["KSampler"]]["inputs"].get("sampler_name"),
            "prompt": PROMPT, "negative_prompt": NEGATIVE,
            "generation_time": generation_time,
            "comfyui_prompt_id": prompt_id,
            "timestamp": utc_now(),
            "reference_conditioning": False,
            "output": str(output.resolve()),
            "comfyui_system": health.get("system", {}),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        manifest["scenes"][0]["shots"][0].update(image_status="complete", image_path=str(output.resolve()))
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        diagnostic["visual_manifest"] = "PASS"
        audit.emit("VISUALS_COMPLETED", scene_id=SCENE_ID, shot_id=SHOT_ID, duration=generation_time)
        print(json.dumps({"status": "PASS", "diagnostic": diagnostic, "output": str(output), "metadata": str(metadata_path)}, indent=2))
        return 0
    except Exception as exc:
        manifest["scenes"][0]["shots"][0]["image_status"] = "failed"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        write_failure_report(output_dir, exc, scene_id=SCENE_ID, shot_id=SHOT_ID, prompt_id=prompt_id or getattr(exc, "prompt_id", None))
        audit.emit("VISUALS_FAILED", scene_id=SCENE_ID, shot_id=SHOT_ID, error=f"{type(exc).__name__}: {exc}")
        print(json.dumps({"status": "FAIL", "diagnostic": diagnostic, "error_type": type(exc).__name__, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
