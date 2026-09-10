"""Generate the canonical master illustration and segment it into named
body-part PNGs.

Reuses app.images.character_illustration (reference-conditioned generation
via Pollinations/ComfyUI, with the existing quality gate and seed-retry
logic) and app.images.production_assets.extract_character_rig (20-part
segmentation with joint/parent/pivot metadata and dilated-mask overlap at
joints) rather than re-implementing image generation or segmentation.

Do NOT fabricate parts with independent per-part prompts: every part here
comes from segmenting the ONE approved master illustration, so proportions,
clothing, lighting, and identity are guaranteed consistent by construction.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.images.character_illustration import illustrate_character

# This project's spec names each part <type>_<side>; extract_character_rig's
# manifest names each part <side>_<type>. Semantically identical, different
# word order - map one to the other explicitly rather than assuming they line up.
PART_NAME_MAP = {
    "head": "head",
    "torso": "torso",
    "upper_arm_L": "left_upper_arm", "lower_arm_L": "left_lower_arm", "hand_L": "left_hand",
    "upper_arm_R": "right_upper_arm", "lower_arm_R": "right_lower_arm", "hand_R": "right_hand",
    "upper_leg_L": "left_upper_leg", "lower_leg_L": "left_lower_leg", "foot_L": "left_foot",
    "upper_leg_R": "right_upper_leg", "lower_leg_R": "right_lower_leg", "foot_R": "right_foot",
}


def generate_parts(entry: dict, char_dir: Path, style: str = "") -> dict:
    """Generate the master illustration, segment it, and copy the 14
    rig-relevant parts (spec above) into char_dir/parts/ under this
    project's naming convention. Returns the updated character entry
    (illustrated_reference / rig_manifest paths from extract_character_rig).

    A missing individual part (e.g. no hair pixels detected) is skipped, not
    fabricated - see extract_character_rig's own per-part bbox check.
    """
    updated = illustrate_character(dict(entry), char_dir.parent, style=style, char_dir=char_dir)
    rig_manifest_path = updated.get("rig_manifest")
    if not rig_manifest_path:
        return updated
    source_dir = Path(rig_manifest_path).parent
    parts_dir = char_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for spec_name, internal_name in PART_NAME_MAP.items():
        source = source_dir / f"{internal_name}.png"
        if source.is_file():
            shutil.copy2(source, parts_dir / f"{spec_name}.png")
            copied.append(spec_name)
    updated["parts_dir"] = str(parts_dir.resolve())
    updated["parts_generated"] = copied
    updated["parts_missing"] = sorted(set(PART_NAME_MAP) - set(copied))
    return updated
