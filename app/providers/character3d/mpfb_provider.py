"""Zero-cost local character generation through MPFB running inside Blender."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.providers.character3d.base import (
    Character3DAsset,
    Character3DProvider,
    CharacterGenerationBlocked,
    CharacterModelValidation,
)
from app.three_d.runner import BlenderRenderProvider, find_blender


class MPFBCharacter3DProvider(Character3DProvider):
    """Build a rigged parametric human locally; no network API or usage fee."""

    name = "mpfb_local"

    def __init__(self, blender_executable: str | None = None) -> None:
        self.blender_executable = blender_executable or find_blender()
        self.worker = Path(__file__).resolve().parents[3] / "blender_worker" / "generate_mpfb_character.py"

    @property
    def configured(self) -> bool:
        return bool(
            self.blender_executable
            and Path(self.blender_executable).is_file()
            and self.worker.is_file()
        )

    def _generate(self, specification: dict[str, Any], output_dir: Path) -> Character3DAsset:
        if not self.configured:
            raise CharacterGenerationBlocked(
                "Blender 4.2+ and the free MPFB extension must be installed locally."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        spec_path = output_dir / "character_spec.json"
        model_path = output_dir / "character_model.glb"
        report_path = output_dir / "generation_report.json"
        spec_path.write_text(json.dumps(specification, indent=2), encoding="utf-8")
        command = [
            self.blender_executable,
            "--background",
            "--python-exit-code",
            "1",
            "--python",
            str(self.worker),
            "--",
            "--spec",
            str(spec_path.resolve()),
            "--output",
            str(model_path.resolve()),
            "--report",
            str(report_path.resolve()),
        ]
        subprocess.run(command, check=True)
        if not model_path.is_file() or not report_path.is_file():
            raise RuntimeError("MPFB did not produce its model and generation report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return Character3DAsset(
            character_id=str(specification.get("character_id", "character")),
            model_path=model_path,
            format="glb",
            provider=self.name,
            materials=tuple(report.get("materials", ())),
            textures=tuple(report.get("textures", ())),
            rigged=int(report.get("bone_count", 0)) > 0,
            facial_rig=int(report.get("shape_key_count", 0)) > 0,
            metadata={**report, "cost_inr": 0, "offline": True},
        )

    def generate_from_text(self, specification, output_dir):
        return self._generate(specification, output_dir)

    def generate_from_images(self, specification, references, output_dir):
        if references:
            specification = {
                **specification,
                "reference_images": [str(path) for path in references],
                "reference_policy": "local_design_guidance_only",
            }
        return self._generate(specification, output_dir)

    def generate_variation(self, canonical, specification, output_dir):
        return self._generate(specification, output_dir)

    def validate_model(self, asset):
        report_path = asset.model_path.with_suffix(".validation.json")
        report = BlenderRenderProvider(self.blender_executable).validate_character_model(
            asset.model_path, report_path
        )
        return CharacterModelValidation(
            passed=bool(report.get("passed")),
            quality_status=str(report.get("quality_status", "rejected")),
            model_format=asset.format,
            vertex_count=int(report.get("vertex_count", 0)),
            triangle_count=int(report.get("triangle_count", 0)),
            materials=tuple(report.get("materials", ())),
            textures=tuple(report.get("textures", ())),
            rig_status=str(report.get("rig_status", "not_tested")),
            facial_rig_status=str(report.get("facial_rig_status", "not_tested")),
            rejection_reasons=tuple(report.get("rejection_reasons", ())),
        )
