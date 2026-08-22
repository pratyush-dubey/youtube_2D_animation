"""Technical gate for diffusion masters; semantic anatomy remains a manual gate."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageStat


def inspect_diffusion_master(path: Path) -> dict:
    if not path.is_file():
        return {"technical_pass": False, "manual_review_required": True, "problems": ["file_missing"]}
    try:
        with Image.open(path) as source:
            source.load()
            rgb = source.convert("RGB")
            width, height = source.size
            grayscale = rgb.convert("L")
            entropy = round(grayscale.entropy(), 3)
            edge_mean = round(ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES)).mean[0], 3)
            colors = rgb.resize((192, 192), Image.Resampling.BILINEAR).quantize(colors=256).getcolors()
            unique_colors = len(colors or [])
    except Exception as exc:
        return {"technical_pass": False, "manual_review_required": True, "problems": [f"decode_failed: {exc}"]}
    checks = {
        "resolution_512x768_or_better": width >= 512 and height >= 768,
        "portrait_aspect": height > width,
        "detail_entropy": entropy >= 5.0,
        "edge_detail": edge_mean >= 4.0,
        "color_complexity": unique_colors >= 128,
    }
    semantic = {
        "full_body": "manual_review_required", "head_visible": "manual_review_required",
        "hands_visible": "manual_review_required", "feet_visible": "manual_review_required",
        "face_quality": "manual_review_required", "anatomy": "manual_review_required",
        "clean_silhouette": "manual_review_required", "no_extra_limbs": "manual_review_required",
    }
    return {
        "technical_pass": all(checks.values()), "manual_review_required": True,
        "production_approved": False, "checks": checks, "semantic_checks": semantic,
        "metrics": {"width": width, "height": height, "entropy": entropy, "edge_mean": edge_mean, "unique_colors_256": unique_colors},
        "problems": [name for name, passed in checks.items() if not passed],
        "next_gate": "Visually inspect the unmodified diffusion PNG. Do not segment or animate until approved.",
    }
