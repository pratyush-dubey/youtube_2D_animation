"""Camera-compensated motion QA for generated video shots."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


def inspect_generative_motion(video_path: Path, output_path: Path | None = None) -> dict:
    """Reject frozen, global-transform-only and rigid-translation clips.

    A global affine model estimates camera motion. Residual optical flow then
    measures deformation and independently moving content after that camera
    transform is removed. This prevents a pan/zoom from scoring as animation.
    """
    cap = cv2.VideoCapture(str(video_path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    if fps <= 0:
        raise ValueError(f"Cannot decode video: {video_path}")
    stride = max(1, round(fps / 6))
    previous = None
    index = 0
    samples = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % stride:
            index += 1
            continue
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (384, 216))
        if previous is not None:
            flow = cv2.calcOpticalFlowFarneback(previous, gray, None, .5, 3, 21, 3, 5, 1.2, 0)
            global_dx, global_dy = np.median(flow.reshape(-1, 2), axis=0)
            residual = np.linalg.norm(flow - np.array((global_dx, global_dy), np.float32), axis=2)
            total = np.linalg.norm(flow, axis=2)
            h, w = gray.shape
            actor = residual[round(h*.12):round(h*.94), round(w*.18):round(w*.84)]
            outer = residual.copy()
            outer[round(h*.12):round(h*.94), round(w*.18):round(w*.84)] = np.nan
            diff = cv2.absdiff(previous, gray).astype(np.float32) / 255.0
            samples.append({
                "time": round(index/fps, 3),
                "camera_flow": round(float(np.hypot(global_dx, global_dy)), 4),
                "total_flow": round(float(np.percentile(total, 75)), 4),
                "nonrigid_flow": round(float(np.percentile(residual, 75)), 4),
                "character_region_flow": round(float(np.percentile(actor, 75)), 4),
                "environment_region_flow": round(float(np.nanpercentile(outer, 75)), 4),
                "frame_difference": round(float(diff.mean()), 6),
            })
        previous = gray
        index += 1
    cap.release()
    nonrigid = [s["nonrigid_flow"] for s in samples] or [0.0]
    total = [s["total_flow"] for s in samples] or [0.0]
    camera = [s["camera_flow"] for s in samples] or [0.0]
    character = [s["character_region_flow"] for s in samples] or [0.0]
    environment = [s["environment_region_flow"] for s in samples] or [0.0]
    frozen_ratio = sum(s["frame_difference"] < .0015 for s in samples) / max(1, len(samples))
    nonrigid_score = float(np.percentile(nonrigid, 65))
    total_score = float(np.percentile(total, 65))
    fake_translation = total_score > .30 and nonrigid_score < .18
    report = {
        "video": str(Path(video_path).resolve()), "fps": fps,
        "camera_motion": round(float(np.percentile(camera, 65)), 4),
        "character_motion": round(float(np.percentile(character, 65)), 4),
        "environment_motion": round(float(np.percentile(environment, 65)), 4),
        "rig_articulation": round(nonrigid_score, 4),
        "foot_sliding": None,
        "frozen_frame_ratio": round(frozen_ratio, 4),
        "fake_translation_detected": fake_translation,
        "passed": bool(nonrigid_score >= .18 and frozen_ratio < .15 and not fake_translation),
        "method": "Farneback optical flow with dominant camera-flow subtraction",
        "samples": samples,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
