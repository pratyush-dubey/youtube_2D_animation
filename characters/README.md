# Character Foundation (Phase 2)

Persistent character-identity system for the Blender-puppet rebuild. See
`docs/ARCHITECTURE_AUDIT.md` for the full rebuild context — this package
implements Phase 2 only (character bible + canonical assets), nothing
downstream (Blender rig, animation, AI Director).

```
characters/
├── models/
│   └── character_schema.py   # CharacterSchema (pydantic) — the identity contract
├── generator/
│   ├── character_bible.py    # build_character(): the one entry point
│   ├── reference.py          # real-person reference-photo resolution
│   ├── parts.py              # master illustration + body-part segmentation
│   └── validator.py          # deterministic (non-AI) asset checks
└── assets/
    └── <character_id>/
        ├── character.json
        ├── reference.png
        └── parts/
            ├── head.png
            ├── torso.png
            ├── upper_arm_L.png / lower_arm_L.png / hand_L.png
            ├── upper_arm_R.png / lower_arm_R.png / hand_R.png
            ├── upper_leg_L.png / lower_leg_L.png / foot_L.png
            └── upper_leg_R.png / lower_leg_R.png / foot_R.png
```

## What this reuses (not reimplements)

- **Reference photos**: `app.images.character_references.resolve_wikimedia_portrait`
  — real-person Wikipedia/Wikimedia lookup, fixed this session to also check
  the page-summary API and locally-hosted (non-Commons) fair-use images.
- **Master illustration + segmentation**: `app.images.character_illustration.illustrate_character`
  and `app.images.production_assets.extract_character_rig` — reference-conditioned
  generation (Pollinations kontext / ComfyUI img2img) and 20-part cutout
  segmentation with joint/parent/pivot metadata and dilated-mask overlap at
  joints (prevents visible gaps when a part later rotates).

`generator/parts.py::PART_NAME_MAP` translates between this project's
`<type>_<side>` naming (e.g. `upper_arm_L`) and `extract_character_rig`'s
`<side>_<type>` naming (e.g. `left_upper_arm`) — semantically identical body
parts, just different filename word order.

## Usage

```python
from characters.models.character_schema import CharacterSchema
from characters.generator.character_bible import build_character

schema = CharacterSchema(
    character_id="albert_einstein",
    name="Albert Einstein",
    age=45, gender_presentation="male",
    face="deep-set thoughtful eyes, high forehead, bushy mustache",
    hair="wild grey-white hair", skin_tone="fair",
    body="average build, slightly stooped posture",
    clothing="rumpled tweed jacket, loose cardigan, no tie",
    art_style="cinematic 2D illustrated documentary",
    is_real_person=True,
)
report = build_character(schema)
```

`build_character` is idempotent: if `character.json` and `reference.png`
already exist for that `character_id`, it returns the cached result rather
than regenerating (pass `force=True` to rebuild).

If no reference photo can be resolved for a named real person, the build
stops there (`blocked: True` in the report) rather than inventing a face —
this is a deliberate policy, not a bug: fix the name/spelling, supply a
reference image manually, or set `is_real_person=False` for a fictional
character.

## Deliberately not deterministic-AI-scored

`generator/validator.py` only checks mechanical properties (file exists,
valid PNG, alpha channel present, not fully transparent, not an accidental
solid-color fill, reasonable dimensions) — not the existing heuristic
composition/silhouette quality gate (`app.images.production_assets.evaluate_asset`).
That stronger gate remains available and is still applied inside
`illustrate_character` during generation; this validator is a second,
cheap, fully-deterministic sanity pass on the resulting files.

## Not built yet (later phases)

Blender rig building, IK, the animation library/semantic API, the AI
Director, camera system, shot JSON, and the frontend timeline are explicitly
out of scope for this phase — see `docs/ARCHITECTURE_AUDIT.md` §7 for the
phase map and what already exists toward each of them.
