"""Ollama-directed, schema-validated shot planning."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from app.cinematic.models import ArtDirection, CameraPlan, CharacterBible, LayerPlan, ShotPlan


HISTORICAL_1980S_BENGALURU = (
    "1980s Bengaluru architecture and signage",
    "period-appropriate Indian clothing and bank furniture",
    "period vehicles only",
    "landline telephones and paper ledgers; no smartphones or modern screens",
)


class ShotPlanner:
    def __init__(self, director=None, art_direction: ArtDirection | None = None) -> None:
        self.director = director
        self.art_direction = art_direction or ArtDirection()

    def plan_bank_proof(self) -> tuple[CharacterBible, list[ShotPlan]]:
        character = CharacterBible(
            character_id="bank_employee_adult",
            name="Arun Rao",
            fictional=True,
            age_stage="adult",
            heritage="Indian",
            face="oval face, expressive brown eyes, defined natural brow and jaw",
            hair="short side-parted black hair",
            skin="medium warm-brown complexion",
            body="lean average adult build",
            clothing="1980s pale cotton collared shirt, dark tailored trousers, leather shoes",
            colors=("aged cream", "charcoal", "warm brown"),
        )
        definitions = [
            ("bank_01", "wide", "2.5d", "approach", "observant", "environment", "wide establishing", 35, "slow_dolly_forward", 0.12, "bank facade", ("pedestrians", "period vehicle", "dust"), "cut"),
            ("bank_02", "tracking", "2.5d", "walk", "neutral", "full_body", "full-body tracking", 50, "track_character", 0.34, "walking character", ("passing pedestrian", "cloth sway", "ground shadow"), "cut"),
            ("bank_03", "medium", "2.5d", "enter", "observant", "medium", "interior medium", 55, "follow_character", 0.18, "doorway and character", ("ceiling fan", "employees", "paper movement", "light flicker"), "cut"),
            ("bank_04", "medium_close", "2d", "look_around", "focused", "medium", "medium close-up", 70, "slow_push", 0.10, "head and eyes", ("eye movement", "head turn", "breathing"), "cut"),
            ("bank_05", "closeup", "2d", "look_to_counter", "focused", "closeup", "dedicated close-up", 85, "micro_dolly", 0.06, "eyes and face", ("blink", "eye movement", "breathing"), "cut"),
            ("bank_06", "sitting", "2.5d", "sit", "resolved", "sitting", "medium-wide sitting", 48, "lateral_slide", 0.14, "chair and character", ("sit pose sequence", "chair contact", "foreground ledger"), "fade_to_black"),
        ]
        shots = []
        for index, item in enumerate(definitions):
            shot_id, shot_type, mode, action, emotion, art_kind, framing, lens, movement, strength, focus, motion, transition = item
            layers = self._layers(character_present=index > 0, atmosphere=True)
            prompt = self._prompt(
                character, shot_id, framing, action, emotion, focus,
                "1980s Bengaluru bank exterior" if index == 0 else "1980s Bengaluru bank interior",
                art_kind,
            )
            shots.append(ShotPlan(
                shot_id=shot_id, start=index * 5.0, duration=5.0, shot_type=shot_type,
                animation_mode=mode, action=action, emotion=emotion,
                character_pose=f"{action}_{emotion}", artwork_kind=art_kind,
                camera=CameraPlan(framing, lens, "eye-level", movement, strength, focus),
                layers=layers, lighting="warm directional daylight with cool interior fill",
                atmosphere=("subtle dust", "soft volumetric light"),
                environment_motion=motion, transition=transition, image_prompt=prompt,
                historical_constraints=HISTORICAL_1980S_BENGALURU,
                character_id=None if index == 0 else character.character_id,
                audio={"sfx": list(motion), "music_mood": "restrained observational"},
            ))
        self.validate(shots)
        return character, shots

    def request_director_review(self, story: str, shots: list[ShotPlan]) -> dict[str, Any]:
        if self.director is None:
            return {"status": "not_requested"}
        prompt = (
            "You are the local AI cinematographer. Review the six-shot plan for action clarity, "
            "historical continuity, meaningful motion, and avoidance of slideshow behavior. "
            "Do not change the 30-second timing. Return JSON with approved, problems, fixes.\n"
            f"Story: {story}\nPlan: {json.dumps([shot.to_dict() for shot in shots])}"
        )
        review, response = self.director.generate_json(prompt, temperature=0.1, max_tokens=600)
        review.update({"provider": response.provider, "model": response.model, "cost_inr": 0})
        return review

    @staticmethod
    def validate(shots: list[ShotPlan]) -> None:
        if len(shots) != 6:
            raise ValueError("The acceptance proof requires exactly six shots")
        if round(sum(shot.duration for shot in shots), 3) != 30.0:
            raise ValueError("The acceptance proof must total exactly 30 seconds")
        for previous, current in zip(shots, shots[1:]):
            if current.start != previous.start + previous.duration:
                raise ValueError("Shot timeline contains a gap or overlap")
        if not any(shot.artwork_kind == "closeup" for shot in shots):
            raise ValueError("A dedicated close-up artwork request is required")
        if not any(shot.action == "walk" for shot in shots):
            raise ValueError("A real walking-animation shot is required")

    def _prompt(self, character, shot_id, camera, action, emotion, focus, location, artwork_kind):
        character_text = "no principal character" if artwork_kind == "environment" else (
            f"the same fictional adult Indian man from character bible {character.character_id}; "
            f"{character.face}; {character.hair}; {character.skin}; {character.clothing}"
        )
        return (
            f"SHOT {shot_id}. SUBJECT: {character_text}. ACTION: {action}, emotion {emotion}. "
            f"LOCATION: {location}. TIME PERIOD: 1980s. CAMERA: {camera}, focus on {focus}. "
            f"COMPOSITION: artwork designed specifically as {artwork_kind}, safe 16:9 frame, "
            "clear foreground, midground, and background separation. LIGHTING: cinematic warm daylight "
            "with motivated practical bounce. ATMOSPHERE: fine dust and lived-in air. "
            f"{self.art_direction.prompt_block()} PERIOD CONSTRAINTS: "
            f"{'; '.join(HISTORICAL_1980S_BENGALURU)}."
        )

    @staticmethod
    def _layers(character_present: bool, atmosphere: bool) -> tuple[LayerPlan, ...]:
        values = [
            LayerPlan("sky_light", "lighting", 0.02, 0.03),
            LayerPlan("far_background", "background", 0.12, 0.06),
            LayerPlan("architecture", "background", 0.30, 0.18),
            LayerPlan("midground", "environment", 0.48, 0.34),
        ]
        if character_present:
            values.append(LayerPlan("character", "character", 0.62, 1.0))
        values.extend([
            LayerPlan("foreground", "foreground", 0.82, 1.45),
            LayerPlan("atmosphere", "fx", 0.90, 0.72, atmosphere),
            LayerPlan("lighting_fx", "lighting", 0.96, 0.55),
        ])
        return tuple(values)
