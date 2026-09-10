# Architecture Audit — Rebuild to a Rigged Blender Puppet Pipeline

Date: 2026-08-24
Scope: Phase 1 of the rebuild spec (repository audit). Written before any Phase-3-onward code changes.

---

## 1. Current pipeline, as it actually runs today

```
FastAPI app (app/api/app.py)
  -> POST /api/director/projects  (director_ui.py / routes/director.py)
  -> Director.execute() runs a dependency graph of SpecializedDirectors (app/director/director.py):

     research -> story -> script -> voice -> timeline -> characters -> visuals
        -> shots -> animation -> sound -> music -> rendering -> subtitles
        -> seo -> thumbnail -> quality -> youtube

  Each stage wraps one Agent (app/agents/*.py). Progress/state is persisted to
  output/<project_id>/director_state.json and to SQLite (PipelineJob/PipelineLog,
  app/database/models.py) so jobs survive restarts. A minimal embedded-HTML UI
  (app/api/routes/director_ui.py) polls state and shows a stage list.
```

Rendering, specifically (the part this rebuild targets):

```
script sections -> per-sentence narration (VoiceAgent, Piper TTS)
  -> TimelineDirector groups sentences back into scenes by script section
     (app/director/director.py:249-385, added this session)
  -> AssetAgent generates ONE illustrated environment plate per scene
     (Pollinations/ComfyUI text-to-image or img2img, app/agents/asset_agent.py)
  -> production_assets.py::extract_character_rig segments an approved character
     illustration into 20 named transparent PNG parts + a rig.json manifest
  -> app/video/animated_renderer.py + illustrated_rig.py: a pure-Pillow,
     per-frame renderer. Camera pan/zoom/crop over the environment plate;
     the character rig.json's parts are mesh-warped (cv2.remap, weighted by
     distance to named 2D joints) frame-by-frame to fake bends at
     elbows/knees/etc. NO 3D, no bpy, no bones — this is the "flat image +
     manual PNG layers + PIL warp" approach the rebuild spec explicitly
     rejects as the primary system.
  -> FFmpeg muxes narration/SFX per scene, concatenates scenes, burns
     subtitles, mixes music (app/agents/video_edit_agent.py).
```

---

## 2. What is genuinely working today (verified live this session, not just read)

These were exercised end-to-end with real subprocess calls (Piper, FFmpeg, ffprobe, live Wikipedia/Wikimedia API calls) during this session, not just inspected as code:

- **VoiceAgent + Piper TTS**: real WAV synthesis, 11-14 real segments per test script, correct per-sentence emotion-driven delivery (after today's fix).
- **TimelineDirector's scene grouping**: sentences correctly grouped by script section (verified: 11 sentences -> 6 scenes matching section boundaries exactly).
- **VideoEditAgent's render + concat + mux**: a full 6-scene test video rendered end-to-end, correct audio duration (29.63s matching the 29.6s expected exactly after today's fixes), narration audible and non-silent (confirmed via `astats`).
- **Character reference resolution** (`app/images/character_references.py`): live-tested against Wikipedia/Wikimedia for two real historical figures (Indira Gandhi — worked before and after this session's fix; R.N. Kao — fixed this session, now resolves and downloads his actual portrait with correct fair-use license metadata).
- **ComfyUI + vendored Blender discovery**: ComfyUI confirmed running and reachable at `127.0.0.1:8188` in CPU mode; `.tools/blender/blender-5.2.0-windows-x64/blender.exe` confirmed present and wired via `app/three_d/runner.py::find_blender()`.
- **MPFB 3D character generation** (`blender_worker/generate_mpfb_character.py` via `app/providers/character3d/mpfb_provider.py`): proven, on this exact machine, to produce a real 19,158-vertex / 163-bone / 65-shape-key rigged, textured, materialed humanoid GLB (`output/character_generation_test/generation_report.json`). This is the single most important discovery for this rebuild — see §4.
- **Job/state system**: `PipelineJob`, `PipelineLog`, `Asset`, `AudioFile`, `Video`, `Metadata`, `YouTubeUpload` SQLAlchemy models (`app/database/models.py`) already implement queued/running/complete/failed job tracking with per-stage logs and cost tracking — this substantially pre-satisfies rebuild-spec Phase 21 (job system) and Phase 22 (logging).
- **Research/Script/SEO/Thumbnail/YouTube-upload agents**: unit + integration tested (273/277 tests passing this session; the failures are pre-existing, unrelated, network-dependent test-isolation bugs, not pipeline defects).

## 3. What was broken and fixed this session (context for "fragile assumptions")

These are documented in detail in commit history / session notes; summarized here because they inform which modules are trustworthy vs. still fragile:

1. Prompt truncation causing near-identical generated scenes across unrelated topics (`asset_agent.py`).
2. ComfyUI generation timeout silently using 600s instead of the configured 900s; reference photos cropped instead of padded, discarding body area needed for full-body img2img (`app/characters/provider.py`, `app/image_generation/comfyui_client.py`).
3. Piper TTS executable-path env var not read from `.env` (`app/audio/voice_provider.py`).
4. Every narration line spoken with an identical hardcoded "serious" emotional delivery, and background-music mood hardcoded to one literal regardless of content (`app/agents/voice_agent.py`, `app/timeline/master.py`).
5. **Slideshow root cause**: every narration *sentence* got its own fresh illustration and independently-rendered clip. Fixed by grouping sentences into scenes by script section (`app/director/director.py`).
6. **Narration bug A**: after fix #5, `VoiceAgent`'s per-sentence-keyed `narration_files` dict was never rekeyed to the new grouped scene numbering — most scenes played the wrong sentence's audio. Fixed via `_grouped_narration_files()` (`app/director/director.py`).
7. **Narration bug B (pre-existing, not introduced this session)**: `app/video/timeline.py::_shot()` silently dropped `master_start`/`master_end` during shot normalization, which meant `VideoEditAgent._concat_clips`'s exact-hard-cut path could never trigger — **every scene cut in every video ever produced by this pipeline** used a ~0.45s crossfade that trimmed/overlapped real narration audio at every cut. Fixed by preserving those two fields through normalization.
8. Retry classifier (`app/agents/base.py::is_retryable_exception`) defaulted to **not** retrying anything that didn't look like a network error — meaning a one-off local subprocess crash (confirmed transient: a Piper CLI crash that succeeded on manual retry) got zero automatic retries despite `max_retries=2` being configured, for any agent. Flipped to retry-by-default, deny-list only genuinely permanent failures.
9. Wikipedia real-person portrait resolution silently failed for at least one documented figure (R.N. Kao) because (a) the `pageimages` API prop has no data for his article despite it having a portrait, and (b) even if it did, the code only checked Wikimedia Commons — his actual portrait is a non-free, locally-hosted file on English Wikipedia (typical for fair-use portraits of deceased officials). Fixed with a REST-summary-API fallback and a local-Wikipedia imageinfo fallback.
10. `app/cinematic/` (a parallel, unused Python 2D compositor) and `renderer/depth_parallax/` (an unused Three.js depth-parallax renderer) were confirmed to have zero real callers and were deleted.

**Takeaway for the rebuild**: everything *upstream* of rendering (research, story, script, TTS, music selection, character identity/reference resolution, job/state tracking, FFmpeg assembly, SEO/thumbnail/YouTube) is real, tested, and now meaningfully more correct than it was this morning. The part that is fundamentally the wrong architecture — not just buggy — is specifically the **Pillow mesh-warp character renderer** (`app/video/animated_renderer.py` + `illustrated_rig.py`), exactly as the rebuild spec identifies.

---

## 4. Full inventory of the existing Blender/3D infrastructure

This is the most consequential finding of this audit: **the README's framing of this as a minor "experimental path, not primary production" undersells what already exists.** There is substantially more real, working Blender automation here than the current pipeline uses.

### 4.1 `blender_worker/` (9 modular files, standalone subprocess scripts — not yet called from `app/`)

| File | Status |
|---|---|
| `scene_builder.py` | Real. Orchestrates a full scene build; hard-requires a passing `quality_report.production_ready == true` before it will render at all (by design — no automatic promotion). |
| `character_loader.py` | Real. Imports a validated character model; explicitly contains a rejection string ensuring it never falls back to a primitive mannequin. |
| `rig_manager.py` | **Dead.** A hardcoded 17-bone from-scratch humanoid skeleton builder. Real bpy code, but not called anywhere in the current pipeline; only asserted to *exist* by one test. Candidate for deletion rather than extension (superseded by MPFB's own rig, see 4.3). |
| `animation_manager.py` | **Dead/orphaned** in the same sense — hand-authored fixed keyframe sequences, not driven by anything upstream, not called by the live pipeline. |
| `camera_manager.py`, `lighting_manager.py`, `material_manager.py`, `environment_manager.py`, `render_manager.py` | Real, functioning scene-construction/render helpers (cinematography, lighting, cel-shade/toon materials, environment dressing, frame rendering). Not wired to a live caller yet, but self-consistent and reusable. |
| `cutout_rig_builder.py` **(added yesterday)** | **Real, working, non-trivial.** Builds a genuine `bpy` armature (`build_armature()`) from the exact `rig.json` manifest produced by `extract_character_rig()` (see §4.4) — creates edit bones, sets parent hierarchy, and calls `bone.align_roll()` with a documented rationale for why this specific fix was needed (references a previous "scissoring/edge-on vanishing" bug). `add_ik()` builds real 3-bone IK chains (wrist/ankle targets + pole-free axis-locked angle limits) via genuine `pose_bone.constraints.new("IK")`. `build_puppet()` rigidly parents flat textured planes to bones via `CHILD_OF` constraints (deliberately not soft-body/weight-paint — matches the rebuild spec's explicit "rigid bone parenting... not soft-body" instruction in §5). **This is the single best existing starting point for rebuild Phase 4 + Phase 6**, but it is not yet invoked from any `app/` code — it only runs as a standalone script. |
| `walk_cycle_test.py` **(added yesterday)** | Real. Drives the above armature's IK targets through a sine-based gait cycle tuned from the rig's own measured rest-pose bone lengths, renders frame-by-frame. Standalone only; no artifacts on disk proving it has actually been run yet. |
| `render_still.py` | Real, minor sanity-check single-frame render helper. |
| `cinematic_2d25d_proof.py` | A **separate, unrelated** proof-of-concept: hand-built parallax planes + an 18-part flat "paper doll" built from procedural mesh vertices, parented via plain `obj.parent` (no armature at all) and hand-keyframed. This is essentially the same technique as the Pillow renderer, reimplemented as literal Blender objects — **not** the architecture to build on. Keep only for reference/deletion candidate once `cutout_rig_builder` is wired in.

### 4.2 `app/three_d/`

| File | Status |
|---|---|
| `action_planner.py` | Real, working. Deterministically maps narration text -> ordered semantic action labels (`walk`, `turn`, `sit`, `talk`, `reach`, `open`, `look`, falling back to `idle`) with blend-in/out timing. This is a genuine, if narrow, precedent for rebuild Phase 8/Phase 9's "semantic animation API" concept — it produces labels + timing today; it does **not** yet map a label to actual keyframe/bone data on any rig. |
| `providers.py` | Pure interface layer (`ReferenceProvider`/`RigProvider`/`MotionProvider` Protocols, `ProviderRegistry`). Zero concrete implementations of `RigProvider`/`MotionProvider` exist anywhere in the repo. This is exactly the extension point the rebuild's semantic-API/animation-library work should plug into, rather than inventing a parallel registry. |
| `runner.py` | Real, production-grade. `BlenderRenderProvider` is the actual host-side subprocess launcher: locates Blender (env var -> system PATH -> `Program Files` -> vendored `.tools/blender`), runs headless `--background --python` renders, and — importantly — has a real staleness guard (rejects a stale pre-existing output file rather than silently accepting it; verified by a passing test that mocks the subprocess to a no-op and confirms the stale file is still rejected). |
| `styles.py` | Real data (7 named style presets), but **disconnected**: nothing in `blender_worker/` currently reads these presets to configure the renderer; `material_manager.py` hardcodes its own toon-shader graph independently. Needs to be wired in, not rebuilt. |

### 4.3 `app/providers/character3d/` — the 3D character provider abstraction

- `base.py`: clean `Character3DProvider` ABC + frozen dataclasses. Real.
- `blocked_provider.py`: the system default (`settings.character_3d_provider = "blocked"`). Every method raises `CharacterGenerationBlocked`; no primitive fallback exists, confirmed both by code and by an on-disk `blocked` quality report.
- `factory.py`: simple, real factory keyed off `settings.character_3d_provider`.
- `local_provider.py`: imports an already-licensed `.glb/.gltf/.fbx/.obj` the user supplies; does not itself build a rig, only imports whatever rig is already baked into the file.
- `mpfb_provider.py`: **the proven-working path.** Shells out to `blender_worker/generate_mpfb_character.py`, which calls MPFB's own `HumanService.add_builtin_rig(basemesh, "default", import_weights=True)` — a third-party library call, not custom code, but it is real, it runs headless via the vendored Blender install, and it has actually produced a complete rigged, textured, shape-keyed humanoid on this machine (`output/character_generation_test/generation_report.json`: 19,158 vertices, 36,972 triangles, 8 materials, 163 bones, 65 shape keys).

### 4.4 The critical compatibility finding: `extract_character_rig()` already feeds Blender

`app/images/production_assets.py::extract_character_rig` (lines 324-477) segments one approved illustrated character plate into **20 named transparent PNG parts** (`head, neck, torso, clothing, hair, eyes, eyebrows, mouth, left_upper_arm, left_lower_arm, left_hand, right_upper_arm, right_lower_arm, right_hand, left_upper_leg, left_lower_leg, left_foot, right_upper_leg, right_lower_leg, right_foot`) plus a `rig.json` manifest (per-part `pivot`, `joint`, `parent`, pixel `position`/`size`). **This manifest format is exactly what `cutout_rig_builder.py` already consumes** (confirmed by that file's own docstring explicitly citing `extract_character_rig()`). This means: the 2D illustration -> segmentation pipeline built for the *old* Pillow renderer is, unmodified, also the correct asset pipeline for feeding the *new* Blender cutout-puppet armature. No new asset-generation work is required for a 2D-plane Blender puppet — only a caller that wires `extract_character_rig`'s output into `cutout_rig_builder.build_armature()`/`build_puppet()`.

(Naming note: `cinematic_2d25d_proof.py`'s own `PART_ORDER` uses inverted word order, e.g. `upper_arm_left` vs. `left_upper_arm` — semantically equivalent but not string-compatible. Not an issue since that file is a dead-end proof, not the integration point.)

### 4.5 Direct answer to "does anything build a bone armature with IK today?"

- **Yes, for a 2D cutout puppet**: `cutout_rig_builder.py` — real, working, well-reasoned, added yesterday, not yet wired to a caller.
- **Yes but dead, for a from-scratch 3D humanoid**: `rig_manager.py` — real bpy code, unused, candidate for deletion.
- **No, for a custom weight-painted 3D mesh-deforming humanoid**: doesn't exist; the only working mesh-humanoid path (MPFB) uses a third-party rig, not project code. Building this from scratch would be new work, and per this audit's recommendation, likely unnecessary (see §6).
- **No bridge exists yet** from `action_planner.py`'s semantic labels to any of the three animation systems' bone names — each hand-authors its own fixed sequence independently.

### 4.6 Test coverage honesty check

All 9 tests in `tests/unit/test_three_d_pipeline.py` pass, but none of them invoke `bpy` (they can't, outside Blender's own interpreter). Roughly half are safety/policy gates (correctly refuse to fake a character, correctly reject stale renders) rather than proofs of generative capability. The evidence that Blender-side code (armature building, MPFB generation) *actually works* comes only from artifacts on disk in `output/character_generation_test/`, not from CI-style automated tests. This is a real gap the rebuild's Phase 19 (testing) should close — likely via a small number of Blender-hosted smoke tests invoked through `runner.py`'s subprocess pattern, since standard pytest cannot import `bpy` directly.

---

## 5. Verdict: build on this, do not replace it

The existing `blender_worker` + `app/three_d` + `app/providers/character3d` scaffolding should be the foundation for the rebuild, not set aside, because:

1. The subprocess/host-launcher plumbing (`runner.py`, vendored-Blender discovery, resumable rendering, staleness guards) is production-grade today.
2. MPFB character generation is proven end-to-end on this machine, for free, producing a real 163-bone rigged, textured, shape-keyed humanoid — this plausibly obviates building a from-scratch mesh-deforming rig builder (rebuild spec Phase 4/5) entirely, if a real 3D mesh humanoid (rather than a 2D-plane cutout puppet) is the desired look.
3. `cutout_rig_builder.py`'s IK implementation (3-bone chains, axis locks, angle limits, documented reasoning) is a direct, working reference for rebuild Phase 6, and generalizes to a full 3D biped by relaxing its current 2D-plane single-axis lock.
4. The quality-gate philosophy across this codebase (`CharacterGenerationBlocked`, strict validators, mtime-staleness checks, tests that grep for forbidden primitive-fallback patterns) is exactly the safety posture the rebuild should extend, not rebuild.
5. `extract_character_rig()`'s 20-part segmentation is already the right asset format for a cutout-puppet approach — zero new asset-generation work needed there.

**What genuinely needs to be built new** (not present anywhere today):
- A concrete `RigProvider`/`MotionProvider` implementation plugged into `app/three_d/providers.py`'s existing (currently empty) registry.
- The semantic-action -> bone-keyframe bridge connecting `action_planner.py`'s output (or a richer AI Story Director per rebuild spec §9) to actual animation on whichever rig is chosen (MPFB's bone names, or a cutout puppet's `rig.json`-derived bone names).
- A caller in `app/` that invokes `cutout_rig_builder.py`/`walk_cycle_test.py` (today they're standalone-only).
- A decision, before Phase 4 implementation, on **which body is the primary target**: (a) MPFB's real 3D mesh humanoid (proven working, heavier, needs MPFB+asset packs installed, currently the closest to "actual character motion" in 3D), or (b) `cutout_rig_builder`'s 2D-plane puppet (lighter, directly reuses the existing illustration pipeline, matches the rebuild spec's literal "characters/<slug>/parts/*.png" file layout example almost exactly). The rebuild spec's own example directory listing (head.png/torso.png/upper_arm_L.png/etc.) matches option (b)'s asset shape, not MPFB's. This audit recommends **(b) as the primary path** for that reason, with MPFB kept available as a richer, opt-in alternative body — but this is a product decision the user should explicitly confirm before Phase 4, since it determines a lot of downstream work.

---

## 6. Retain vs. replace

### Retain as-is
- `app/agents/research_agent.py`, `story_agent.py` (via StoryDirector), `script_agent.py`, `seo_agent.py`, `thumbnail_agent.py`, `youtube_agent.py`, `quality_agent.py` — untouched by this rebuild's concerns.
- `app/audio/*` (voice_provider.py, voicepacks, speech_markup, director.py), `app/agents/voice_agent.py`, `app/agents/music_agent.py` — TTS/music selection, all fixed and verified this session.
- `app/images/character_references.py` — real-person reference-photo resolution, just fixed and verified.
- `app/images/production_assets.py::extract_character_rig` — directly reusable as the asset pipeline for a cutout-puppet Blender rig (§4.4).
- `app/agents/video_edit_agent.py`'s FFmpeg assembly logic (concat, subtitle burn, music mix) — reusable for assembling Blender-rendered frame sequences instead of Pillow-rendered clips; the shot-boundary/exact-clock logic just fixed this session applies equally.
- `app/database/models.py`, `app/api/job_store.py`/`job_runner.py` — job system, already close to spec Phase 21.
- `app/director/director.py`'s graph/dependency/retry framework — reusable to add new stage nodes (rig build, animation, Blender render) without restructuring the whole orchestrator.
- `app/three_d/runner.py`, `app/providers/character3d/*`, `blender_worker/camera_manager.py`/`lighting_manager.py`/`material_manager.py`/`environment_manager.py`/`render_manager.py`/`cutout_rig_builder.py`/`generate_mpfb_character.py` — per §5.
- Frontend shell (`app/api/routes/director_ui.py`) as a starting point — needs the shot-timeline UI added (rebuild Phase 16/20), not a rewrite.

### Replace (primary character-animation path only)
- `app/video/animated_renderer.py` + `app/video/illustrated_rig.py` — the Pillow mesh-warp puppet renderer, exactly as the rebuild spec instructs. Not deleted yet (still the only working renderer until the Blender path is live), but no longer the target architecture. Some concepts inside it are worth preserving as *reference*, not code: the depth-band/parallax layer separation, and the named camera-move vocabulary (`slow_push`, `dolly_in`, `pan_left/right`, `orbit_simulation`, `handheld`/`shake`) map almost directly onto rebuild spec §11's camera-behavior list and could inform the new Blender camera rig's parameter names for continuity.

### Delete/retire candidates (flag for user decision, not yet acted on)
- `blender_worker/rig_manager.py` + `animation_manager.py` — dead, superseded by MPFB's own rig or by `cutout_rig_builder`.
- `blender_worker/cinematic_2d25d_proof.py` — superseded in spirit by `cutout_rig_builder.py`; keep only if wanted as a reference for the parallax-plane technique.

---

## 7. Implementation plan mapped to the rebuild's 17 phases

| Phase | Status after this audit |
|---|---|
| 1. Repository audit | **Done — this document.** |
| 2. One canonical character | Implemented immediately after this document (see below). |
| 3. Character part generation/validation | Mostly **already exists** (`extract_character_rig`, quality gates in `production_assets.py`) — Phase 2's implementation reuses it directly rather than building new. |
| 4. Automated Blender rig builder | **Real starting point exists** (`cutout_rig_builder.py`) but needs (a) the primary-body decision from §5, (b) a caller wiring it into `app/`, (c) generalizing to 3D rotation if MPFB path is chosen instead/also. |
| 5. IK system | **Reference implementation exists** (`cutout_rig_builder.py::add_ik`) — needs generalizing from 2D-plane axis-lock to full 3D if a mesh humanoid is the target. |
| 6-17 | Genuinely new work; §5 above lists exactly what's missing for each. Not started — per your instruction, only Phase 1 and 2 are being done now. |

## 8. First milestone

Per your spec: one canonical character — `character_id`, name, age, gender presentation, face description, hair, skin tone, body proportions, clothing, accessories, color palette, art style, reference image, negative constraints, seed/reference metadata — with a reference sheet generated before body parts, all parts deriving from the same identity, and automatic validation.

Implementation note: this audit found an existing, if inconsistent, persistent character store at `character_library/<slug>/` (already used by `muthappa_rai/` and `fictional_indian_adult/`) rather than the exact `characters/<slug>/` path named in your spec's example. Phase 2 below extends that existing convention (`character_library/`) rather than starting a second, parallel top-level directory — flagging this deviation explicitly rather than silently picking one.
