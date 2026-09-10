"""Build one canonical character: identity -> reference photo -> body-part
assets -> deterministic validation -> character.json.

CANONICAL CHARACTER
    -> REFERENCE SHEET (generator/reference.py)
    -> BODY PART EXTRACTION (generator/parts.py, from the ONE approved master)
    -> VALIDATION (generator/validator.py)
    -> character.json

This is the only entry point that should be used to create a character
under characters/assets/<character_id>/ - it never generates parts
independently of the reference, and it never regenerates a character that
already has a complete, validated set of assets on disk.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from characters.generator.parts import PART_NAME_MAP, generate_parts
from characters.generator.reference import resolve_reference
from characters.generator.validator import validate_parts, validate_reference
from characters.models.character_schema import CharacterSchema

ASSETS_ROOT = Path(__file__).resolve().parents[1] / "assets"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "character"


def build_character(schema: CharacterSchema, *, style: str = "", force: bool = False) -> dict:
    """Build (or reuse) one canonical character. Returns a report dict with
    the resulting CharacterSchema (as a dict), the validation results for
    every generated asset, and an overall `passed` flag.
    """
    char_dir = ASSETS_ROOT / schema.character_id
    character_json = char_dir / "character.json"
    reference_png = char_dir / "reference.png"

    if not force and character_json.is_file() and reference_png.is_file():
        existing = json.loads(character_json.read_text(encoding="utf-8"))
        return {"character": existing, "reused": True, "char_dir": str(char_dir.resolve())}

    char_dir.mkdir(parents=True, exist_ok=True)

    if schema.is_real_person:
        reference_meta = resolve_reference(schema.name, char_dir)
        if not reference_meta:
            # Policy: never invent a face for a named real person. Persist
            # what we know and stop rather than falling through to a
            # generic text-only illustration.
            report = {
                "character": schema.model_dump(),
                "reused": False,
                "char_dir": str(char_dir.resolve()),
                "blocked": True,
                "reason": (
                    f"No Wikipedia/Wikimedia reference portrait could be resolved for "
                    f"'{schema.name}'. Provide reference_image manually or set "
                    f"is_real_person=False for a fictional character."
                ),
            }
            (char_dir / "character.json").write_text(
                json.dumps(report["character"] | {"status": "blocked_no_reference"}, indent=2),
                encoding="utf-8",
            )
            return report
        schema.reference_image = reference_meta["reference_image"]
        schema.reference_source_url = reference_meta.get("reference_source_url", "")
        schema.reference_file_url = reference_meta.get("reference_file_url", "")
        schema.reference_license = reference_meta.get("reference_license", "")
        schema.reference_artist = reference_meta.get("reference_artist", "")
        schema.reference_attribution = reference_meta.get("reference_attribution", "")

    entry = {
        "name": schema.name,
        "character_id": schema.character_id,
        "appearance": schema.appearance_summary(),
        "clothing": schema.clothing,
        "reference_image": schema.reference_image,
        "reference_public_url": schema.reference_source_url,
    }
    generation = generate_parts(entry, char_dir, style=style)
    schema.provider = str(generation.get("illustrated_reference") and "image_generation_pipeline" or "")

    reference_check = validate_reference(reference_png)
    part_checks = validate_parts(char_dir / "parts", list(PART_NAME_MAP))
    all_checks = [reference_check, *part_checks]
    passed = reference_check.passed and any(check.passed for check in part_checks)

    character_dict = schema.model_dump()
    character_dict["status"] = "validated" if passed else "generated_with_issues"
    character_dict["parts_generated"] = generation.get("parts_generated", [])
    character_dict["parts_missing"] = generation.get("parts_missing", [])
    character_json.write_text(json.dumps(character_dict, indent=2), encoding="utf-8")

    return {
        "character": character_dict,
        "reused": False,
        "char_dir": str(char_dir.resolve()),
        "passed": passed,
        "validation": [
            {"part": c.part, "path": c.path, "passed": c.passed, "problems": c.problems}
            for c in all_checks
        ],
    }
