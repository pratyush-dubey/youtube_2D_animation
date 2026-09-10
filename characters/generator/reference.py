"""Resolve the canonical reference photo for a character.

Reuses app.images.character_references (real-person Wikipedia/Wikimedia
portrait resolution — fixed and live-verified against the real APIs earlier
this session) rather than re-implementing portrait lookup here.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.images.character_references import resolve_wikimedia_portrait


def resolve_reference(name: str, char_dir: Path) -> dict:
    """Resolve and save `char_dir/reference.png`. Returns {} if unresolved.

    The character remains blocked from further asset generation (per the
    project-wide no-invented-face-for-a-real-person policy) rather than
    silently falling back to a generic illustration when this returns {}.
    """
    char_dir.mkdir(parents=True, exist_ok=True)
    result = resolve_wikimedia_portrait(name, char_dir)
    if not result:
        return {}
    source = Path(result["reference_image"])
    target = char_dir / "reference.png"
    from PIL import Image
    Image.open(source).convert("RGB").save(target, "PNG")
    result["reference_image"] = str(target.resolve())
    return result
