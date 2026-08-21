"""Orchestrate the bounded six-shot bank proof without silent fallbacks."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image

from app.cinematic.assets import AssetManifest
from app.cinematic.image_provider import BLOCKED_MESSAGE, ImageGenerationBlocked, get_cinematic_image_provider
from app.cinematic.models import ArtDirection
from app.cinematic.quality import inspect_artwork, inspect_plan
from app.cinematic.shot_planner import ShotPlanner


STORY = (
    "An adult Indian bank employee walks into a 1980s Bengaluru bank, looks around, "
    "approaches the counter, and sits down."
)


class CinematicBankProof:
    def __init__(self, output_dir: Path, director=None) -> None:
        self.output_dir = output_dir
        self.direction = ArtDirection()
        self.planner = ShotPlanner(director, self.direction)
        self.provider = get_cinematic_image_provider(output_dir / "cache")
        self.manifest = AssetManifest(output_dir / "assets" / "asset_manifest.json")

    def run(self, plan_only=False) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        character, shots = self.planner.plan_bank_proof()
        plan_quality = inspect_plan(shots)
        director_review = self.planner.request_director_review(STORY, shots)
        existing_review = self.output_dir / "director_review.json"
        if director_review.get("status") == "not_requested" and existing_review.is_file():
            director_review = json.loads(existing_review.read_text(encoding="utf-8"))
        if any(item.get("id") == "bank_06" for item in director_review.get("problems", [])):
            director_review["resolution"] = (
                "Applied: bank_06 uses a gradual fade to black, preserving the requested ending."
            )
        self._write("art_direction.json", self.direction.to_dict())
        self._write("character_bible.json", character.to_dict())
        self._write("shot_plan.json", {"story": STORY, "shots": [shot.to_dict() for shot in shots]})
        self._write("director_review.json", director_review)
        if not plan_quality["passed"]:
            return self._report("rejected", "Shot plan failed acceptance checks", plan_quality, [], director_review)
        if plan_only:
            return self._report("planned", "Plan-only run completed", plan_quality, [], director_review)
        if not self.provider.configured:
            reason = getattr(self.provider, "reason", BLOCKED_MESSAGE)
            return self._report("blocked", reason, plan_quality, [], director_review)

        artwork_reports = []
        character_reference = self.output_dir / "assets/characters/bank_employee_adult/reference.png"
        self.provider.generate_character(
            self._character_prompt(character), character_reference
        )
        self._register(character_reference, "character_reference", character.character_id, "character_bible", "character_ref", self._character_prompt(character))

        for shot in shots:
            output = self.output_dir / "assets/shots" / shot.shot_id / f"{shot.artwork_kind}.png"
            references = () if shot.character_id is None else (character_reference,)
            operation = self._operation_for(shot.artwork_kind)
            getattr(self.provider, operation)(shot.image_prompt, output, references)
            self._register(output, "shot_artwork", shot.character_id, "bank_proof", shot.shot_id, shot.image_prompt)
            artwork_reports.append(inspect_artwork(output, shot.artwork_kind))

        if not all(item["passed"] for item in artwork_reports):
            return self._report("rejected", "Shot artwork failed quality checks", plan_quality, artwork_reports, director_review)
        return self._report(
            "awaiting_layering",
            "Shot-specific artwork passed; segmentation/depth/puppet approval is the next gate.",
            plan_quality,
            artwork_reports,
            director_review,
        )

    def _operation_for(self, kind):
        return {
            "environment": "generate_environment",
            "full_body": "generate_character_pose",
            "medium": "generate_character_pose",
            "closeup": "generate_character_expression",
            "sitting": "generate_character_pose",
        }[kind]

    def _character_prompt(self, character):
        return (
            f"CHARACTER BIBLE REFERENCE SHEET for {character.name}, a fictional {character.age_stage} "
            f"{character.heritage} man. Face: {character.face}. Hair: {character.hair}. "
            f"Skin: {character.skin}. Body: {character.body}. Clothing: {character.clothing}. "
            "Front, three-quarter, profile, and expression studies; natural anatomy; transparent or plain neutral backdrop. "
            + self.direction.prompt_block()
        )

    def _register(self, path, asset_type, character, scene, shot, prompt):
        with Image.open(path) as image:
            resolution = image.size
        self.manifest.register(
            asset_id=f"{shot}_{asset_type}", asset_type=asset_type, character=character,
            scene=scene, shot=shot, resolution=resolution, source="generated",
            provider=self.provider.name, license_name="generated dramatic reconstruction",
            generation_prompt=prompt, path=path,
        )

    def _report(self, status, message, plan_quality, artwork_reports, director_review):
        report = {
            "pipeline": "cinematic_2d25d", "status": status, "message": message,
            "provider": self.provider.name, "provider_model": self.provider.model,
            "zero_cost": self.provider.zero_cost,
            "cost_inr": 0,
            "plan_quality": plan_quality, "artwork_quality": artwork_reports,
            "director_review": director_review,
            "final_video_created": False,
        }
        self._write("production_report.json", report)
        return report

    def _write(self, name, value):
        path = self.output_dir / name
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        return path
