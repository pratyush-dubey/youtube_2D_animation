"""Deterministic asset validation for character parts.

Deliberately NOT the existing AI-scored quality gate
(app.images.production_assets.evaluate_asset, which does heuristic
composition/silhouette scoring) - this is a separate, cheap, fully
deterministic pass over concrete, mechanically-checkable properties. Add the
heuristic gate back in later if warranted; don't conflate the two.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

MIN_DIMENSION = 64
MAX_DIMENSION = 8192
# A part that's >99% one solid opaque color is almost always an accidental
# flat background fill, not real illustrated content.
SOLID_FILL_THRESHOLD = 0.99


@dataclass
class PartValidation:
    part: str
    path: str
    passed: bool
    problems: list[str] = field(default_factory=list)


def validate_part(path: Path) -> PartValidation:
    part = path.stem
    problems: list[str] = []

    if not path.is_file():
        return PartValidation(part, str(path), False, ["file_missing"])

    try:
        from PIL import Image
        image = Image.open(path)
        image.verify()
        image = Image.open(path)  # re-open: verify() leaves the file unusable
    except Exception:
        return PartValidation(part, str(path), False, ["invalid_or_corrupt_png"])

    if image.format != "PNG":
        problems.append("not_png")
    if "A" not in image.mode:
        problems.append("no_alpha_channel")
    width, height = image.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        problems.append("dimensions_too_small")
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        problems.append("dimensions_too_large")

    if "A" in image.mode:
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            problems.append("fully_transparent_blank_image")
        else:
            import numpy as np
            visible_fraction = (
                (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / max(width * height, 1)
            )
            alpha_array = np.asarray(alpha)
            opaque_fraction = float((alpha_array > 250).mean())
            if opaque_fraction > SOLID_FILL_THRESHOLD:
                # Fully opaque across almost the whole canvas: either the
                # transparency was never applied, or it's a flat background
                # fill rather than a cutout character part.
                rgb = np.asarray(image.convert("RGB"))
                if rgb.std() < 3.0:
                    problems.append("solid_color_fill_not_a_cutout")
            if visible_fraction < 0.002:
                problems.append("negligible_visible_content")

    return PartValidation(part, str(path.resolve()), not problems, problems)


def validate_parts(parts_dir: Path, expected: list[str]) -> list[PartValidation]:
    return [validate_part(parts_dir / f"{name}.png") for name in expected]


def validate_reference(reference_path: Path) -> PartValidation:
    """Looser check for the full reference photo/illustration (opaque RGB
    is expected here, unlike a transparent cutout part)."""
    if not reference_path.is_file():
        return PartValidation("reference", str(reference_path), False, ["file_missing"])
    try:
        from PIL import Image
        image = Image.open(reference_path)
        image.verify()
        image = Image.open(reference_path)
    except Exception:
        return PartValidation("reference", str(reference_path), False, ["invalid_or_corrupt_image"])
    problems = []
    width, height = image.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        problems.append("dimensions_too_small")
    return PartValidation("reference", str(reference_path.resolve()), not problems, problems)
