"""Guard against the character sliding on one fixed path in every scene, and
confirm the rig actually articulates a mouth-open amplitude into pixels."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def test_blocking_varies_by_seed_for_the_same_action():
    from app.video.blocking import character_blocking

    first = character_blocking("walk", "medium", seed=1)
    second = character_blocking("walk", "medium", seed=2)
    assert (first["start_x"], first["end_x"]) != (second["start_x"], second["end_x"])


def test_blocking_crossing_action_has_real_travel_span():
    from app.video.blocking import character_blocking

    blocking = character_blocking("walk", "wide", seed=7)
    assert abs(blocking["end_x"] - blocking["start_x"]) > 0.2


def test_blocking_closeup_is_held_near_center():
    from app.video.blocking import character_blocking

    blocking = character_blocking("react", "closeup", seed=3)
    assert blocking["start_x"] == blocking["end_x"]
    assert 0.4 <= blocking["start_x"] <= 0.7


def _build_test_rig(tmp_path):
    from app.images.production_assets import extract_character_rig, remove_subject_background

    source = Image.new("RGB", (1000, 1200), "white")
    draw = ImageDraw.Draw(source)
    draw.ellipse((350, 90, 650, 390), fill="#8b5a3c")
    draw.rounded_rectangle((250, 340, 750, 850), 80, fill="#24553d")
    draw.rectangle((290, 820, 470, 1160), fill="#202c35")
    draw.rectangle((530, 820, 710, 1160), fill="#202c35")
    raw = tmp_path / "raw.png"
    cutout = tmp_path / "cutout.png"
    source.save(raw)
    remove_subject_background(raw, cutout)
    return extract_character_rig(cutout, tmp_path / "rig")


def test_mouth_open_amplitude_moves_pixels(tmp_path):
    from app.video.illustrated_rig import IllustratedCharacterRig

    manifest_path = _build_test_rig(tmp_path)
    rig = IllustratedCharacterRig(manifest_path)

    closed = rig.render(
        400, phase=0.0, action="react", expression="neutral",
        head_turn=0.0, breathing=1.0, mouth_open=0.0,
    )
    open_mouth = rig.render(
        400, phase=0.0, action="react", expression="neutral",
        head_turn=0.0, breathing=1.0, mouth_open=1.0,
    )
    closed_arr = np.asarray(closed, dtype=np.int16)
    open_arr = np.asarray(open_mouth, dtype=np.int16)
    assert closed_arr.shape == open_arr.shape
    assert np.abs(closed_arr - open_arr).sum() > 0
