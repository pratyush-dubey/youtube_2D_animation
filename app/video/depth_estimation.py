"""Monocular depth estimation for the single-mesh parallax renderer.

One depth map per scene image feeds renderer/depth_parallax's vertex-shader
displacement (see scene.js) - this is the only source of "3D-ness" in that
renderer; there are no separate cutout layers to misalign or fragment.

Runs locally on CPU via transformers' depth-estimation pipeline (this machine
has no CUDA GPU). Depth estimation is far lighter than diffusion image
generation, so this is expected to take low single-digit seconds per image,
not the minutes a local Stable Diffusion call takes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import structlog
from PIL import Image

logger = structlog.get_logger(__name__)

_MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline
        logger.info("depth_model_loading", model=_MODEL_ID)
        _pipeline = pipeline(task="depth-estimation", model=_MODEL_ID)
        logger.info("depth_model_loaded", model=_MODEL_ID)
    return _pipeline


def estimate_depth(image_path: Path, output_path: Path) -> Path:
    """Write a single-channel depth PNG (same resolution as the source) to output_path.

    Brighter = nearer, matching scene.js's vertex shader convention
    (`depth * displacementScale` pushes the vertex toward the camera).
    Idempotent: skips inference if output_path already exists, mirroring the
    prompt-hash caching pattern already used for scene images in
    app/agents/asset_agent.py, so re-rendering camera moves doesn't require
    re-running the depth model.
    """
    if output_path.is_file():
        return output_path

    source = Image.open(image_path).convert("RGB")
    depth_pipeline = _get_pipeline()
    result = depth_pipeline(source)
    depth_image = result["depth"]
    if depth_image.size != source.size:
        depth_image = depth_image.resize(source.size, Image.Resampling.LANCZOS)

    depth_array = np.asarray(depth_image.convert("L"), dtype=np.float32)
    depth_min, depth_max = float(depth_array.min()), float(depth_array.max())
    normalised = (depth_array - depth_min) / max(depth_max - depth_min, 1e-6)
    depth_8bit = np.clip(normalised * 255.0, 0, 255).astype(np.uint8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(depth_8bit, "L").save(output_path, "PNG")
    return output_path
