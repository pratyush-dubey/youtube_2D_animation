# AI YouTube Automation

Automated 2D YouTube video generation system.

## Default product: AI Video Director

Normal use is now one request and one button. Run `start_video_generator.bat`,
open `http://127.0.0.1:8000/`, describe the finished video, and select **Create
Video**. Research, scripting, characters, shots, visuals, animation, voice,
sound, music, subtitles, rendering, QA, thumbnail, SEO, and YouTube preparation
run as internal background stages. Character Studio and the production editor
remain available through **Advanced Mode**.

Start with the 60-second option. See [docs/ai_video_director.md](docs/ai_video_director.md)
for the graph, states, quality gate, retry/repair behavior, and local-first setup.

**Script → AI direction → Shot plan → Shot-specific artwork → Layers/depth → 2D puppet + 2.5D parallax → Audio/subtitles → FFmpeg**

Fully cloud-hosted, no GPU required, mostly free to run.

---

## Architecture

The system is built as a **multi-agent pipeline** — each stage of video production is a self-contained `Agent` that reads from and writes to a shared `AgentContext`. Agents are independently retryable, and the pipeline is crash-safe and resumable.

```
TrendAgent         ← finds trending topics (pytrends / YouTube API / LLM fallback)
    │
ResearchAgent      ← Wikipedia + DuckDuckGo + Tavily + LLM
    │
ScriptAgent        ← LLM → structured JSON script with sections
    │
StoryboardAgent    ← LLM → per-scene breakdown with image prompts
    │
AssetAgent         ← Pollinations AI / Stability AI / placeholder
VoiceAgent         ← gTTS / ElevenLabs / pyttsx3
MusicAgent         ← local CC0 library / Free Music Archive download
    │
VideoEditAgent     ← FFmpeg (Ken Burns, subtitles, music ducking)
    │
SEOAgent           ← LLM → titles, description, tags, chapters
ThumbnailAgent     ← Pillow → 1280×720 branded thumbnail
QualityAgent       ← pre-upload file / stream / SEO checks
    │
YouTubeAgent       ← YouTube Data API v3 (always PRIVATE first)
```

### Autonomous Scheduler

APScheduler fires every 3 days, picks a trending topic, runs the full pipeline, and uploads as **PRIVATE**. Human approves before publishing.

---

## Quick start

### 1. Clone and install

```bash
git clone <repo>
cd ai-youtube-automation
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
# Install your chosen LLM library:
pip install google-generativeai   # for Gemini (recommended, free tier)
# or:
pip install openai                # for OpenAI
```

### 2. Configure

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key from https://aistudio.google.com/apikey>
```

### 3. Run a single video

```bash
# Legacy orchestrator (research + script + SEO + thumbnail):
python -m app.main create --topic "How black holes work"

# Full agent pipeline (all 13 agents):
python -m app.main run --topic "How black holes work"

# Full pipeline + YouTube upload (requires YouTube credentials):
python -m app.main run --topic "How black holes work" --upload
```

### 4. Start the autonomous scheduler

```bash
# Run every 3 days for the "science" niche:
python -m app.main scheduler start --niche science

# Run one job immediately, then schedule:
python -m app.main scheduler start --niche space --now

# Trigger one job right now (no recurring schedule):
python -m app.main scheduler trigger --niche history
```

### 5. Manage projects

```bash
# Check pipeline status:
python -m app.main status --project <project_id>

# View API cost breakdown:
python -m app.main cost --project <project_id>

# Publish a private video to public (human approval gate):
python -m app.main publish --project <project_id>
```

---

## Technology stack

| Component | Default (free) | Paid/better alternative |
|---|---|---|
| **LLM** | Gemini 1.5 Flash (free tier) | OpenAI GPT-4o |
| **Research** | Wikipedia + DuckDuckGo (free) | Tavily API (free tier) |
| **Image gen** | Pollinations AI (free, no key) | Stability AI (credits) |
| **TTS** | gTTS (free, internet) | ElevenLabs (free tier 10k/mo) |
| **Video** | FFmpeg (free, local) | — |
| **Music** | CC0 local library | — |
| **Database** | SQLite (local) | PostgreSQL (easy migration) |
| **Scheduler** | APScheduler (free) | — |
| **Hosting** | Railway / Render / Fly.io free tier | — |

---

## Configuration reference

See [`.env.example`](.env.example) for all options with comments.

Key variables:

```env
# LLM
LLM_PROVIDER=gemini            # gemini | openai | ollama
GEMINI_API_KEY=...

# Image generation
IMAGE_PROVIDER=pollinations    # pollinations | stability | gemini | placeholder
STABILITY_API_KEY=             # optional
VISUAL_QUALITY=PRODUCTION      # DEBUG | DRAFT | PRODUCTION
ALLOW_PRIMITIVE_DEBUG_ASSETS=false

# TTS
TTS_PROVIDER=edge_tts          # edge_tts | gtts | elevenlabs | pyttsx3
ELEVENLABS_API_KEY=            # optional

# Research enrichment
TAVILY_API_KEY=                # optional — improves research quality

# Scheduler
SCHEDULER_ENABLED=false
SCHEDULER_INTERVAL_DAYS=3
SCHEDULER_NICHE=science and technology

# YouTube
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_PRIVACY_STATUS=private  # always private until manually published
AUTO_PUBLISH=false
```

### Real-person identity references

Named people are never replaced with invented faces. The character stage keeps only
people explicitly returned by research and attempts to resolve their lead portrait and
license metadata through Wikipedia/Wikimedia Commons. Providers with image conditioning
receive that portrait with the generation prompt. Text-only fallbacks use the verified
archival portrait instead of generating a different person.

For a person whose Wikimedia portrait cannot be resolved, add a reference you have the
right to use at `assets/characters/<full-name-slug>.jpg`; for example,
`assets/characters/a-p-j-abdul-kalam.jpg`. The quality gate blocks unreferenced real-person
character scenes. Procedural characters require `character_is_fictional: true` explicitly.

---

## Niche presets

Use `--niche` to apply pre-tuned style/tone settings:

| Preset | Topic domain | Style | Duration |
|---|---|---|---|
| `science` | Science and technology | Documentary | 8 min |
| `space` | Space exploration | Cinematic | 8 min |
| `history` | World history mysteries | Documentary | 10 min |
| `tech` | AI and future technology | Explainer | 7 min |
| `psychology` | Psychology and behavior | Educational | 7 min |

---

## Project structure

```
app/
├── agents/          # 13 pipeline agents (base, trend, research, script, ...)
├── config/          # Settings (pydantic-settings), structured logging
├── cost/            # Per-project API cost tracker
├── database/        # SQLAlchemy models + session (SQLite / PostgreSQL)
├── llm/             # LLM abstraction (Gemini, OpenAI, Ollama)
├── pipeline/        # Legacy orchestrator + PipelineState machine
├── research/        # Researcher, schemas
├── scheduler/       # APScheduler + niche configs
├── script/          # ScriptGenerator, schemas
├── seo/             # SEO metadata generator
├── thumbnail/       # Pillow thumbnail renderer
├── youtube/         # OAuth2 auth + resumable upload
└── main.py          # CLI (click)

prompts/v1/          # LLM prompt templates (versioned)
assets/music/        # CC0 background music library
output/              # Generated video output (per project_id)
projects/            # SQLite database + YouTube token
tests/               # Unit + integration tests (123 passing)
```

---

## Cinematic animation pipeline

The renderer uses an editable, deterministic scene graph rather than holding one
image for the duration of a scene:

```text
script -> scenes -> shots -> illustrated raster assets -> segmentation/rigging
       -> camera + parallax + articulated character + FX + lighting -> FFmpeg -> MP4
```

Each persisted `production_plan.json` contains multiple shots, depth-sorted
environment/character/FX/lighting layers, camera keyframes, audio clips, a random
seed, and a pre-render animation quality score. Plans below
`ANIMATION_QUALITY_THRESHOLD` (default `70`) are repaired before rendering. If an
AI asset fails, production rendering rejects the asset or reuses accepted cached
illustration. Primitive characters and scenery are available only in explicit DEBUG mode.

Render modes:

- `DRAFT`: low-resolution, fast iteration
- `PREVIEW`: 960-wide animated preview
- `FINAL`: 1080p output at 30 FPS

Visual quality levels:

- `DEBUG`: primitives are allowed only when `ALLOW_PRIMITIVE_DEBUG_ASSETS=true`
- `DRAFT`: illustrated assets with layered parallax preparation
- `PRODUCTION`: illustrated assets, an 80-point quality gate, lighting, texture, rigging, and grading

### Production illustrated-character gate

Character art is a separate, stricter gate. Run it before any animation:

```powershell
python tools/build_character_quality_test.py
```

It writes Arun's canonical `character_bible.json`, `reference_analysis.json`, generation
manifest, master views, poses, `character_beauty_sheet.png`, and `quality_report.json` under
`D:\AI_VIDEO_GENERATOR\character_library\arun\`. It never creates geometric, SVG, placeholder, or primitive
character images. Without a genuine reference-capable local image backend, the report is
`blocked` and contains `generated_images: 0`.

```env
CHARACTER_IMAGE_PROVIDER=auto # auto | comfyui | imported | gemini_image | unconfigured
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_GENERATION_TIMEOUT_SECONDS=1800
IMPORTED_CHARACTER_DIR=assets/imported_characters
```

Run `start_local_ai.bat` to validate the D: installation, start ComfyUI with DirectML, and wait
for its health endpoint. `python tools/model_manager.py --verify` inventories the checkpoint,
size, path, license note, disk space, and SHA-256. `auto` uses local ComfyUI first, approved
imported artwork second, and stops; Gemini is considered only when explicitly selected.
Master art and every pose remain subject to manual visual approval before segmentation and
rigging.

`automatic1111` uses an already-running local Stable Diffusion WebUI. `gemini_image` is a
separate optional image-generation adapter and is never confused with Gemini Flash-Lite
reasoning. It remains blocked while `ZERO_COST_MODE=true`. Prompts, references, style,
resolution, and model identity are content-hashed so unchanged assets are reused.

## Experimental Blender path (not primary production)

The prior provider-neutral 3D work is preserved for experiments. The application writes a
deterministic `production_plan.json`; a background Blender worker constructs the scene,
imports a provider-created character model, validates its humanoid rig, animates bones,
directs a perspective camera, places lights, applies centralized toon materials, renders
resumable frames, and hands the result back to FFmpeg. It is not used by the cinematic
illustrated documentary pipeline.

```env
RENDER_PROVIDER=cinematic_2d25d
BLENDER_PATH=C:/Program Files/Blender Foundation/Blender 5.2/blender.exe
ART_STYLE_PRESET=CINEMATIC_ILLUSTRATED_DOCUMENTARY
```

The older 3D proof can still be run explicitly for development:

```powershell
python tools/render_bank_clerk_3d_proof.py
```

The old sphere/capsule mannequin has been retired from production. There is deliberately
no automatic primitive fallback. A verified reference and a reference-capable
`Character3DProvider` are required before claiming likeness to a real person.

### Experimental 3D character gate

The production character stack is local and has no API usage fee. Supported paths are:

- `mpfb`: generates and rigs a parametric human locally with the GPL MPFB
  Blender extension and CC0 MakeHuman assets.
- `local`: imports a licensed model named by `LOCAL_CHARACTER_MODEL`.
- `blocked` (default): disables 3D character generation without substituting a primitive mannequin.

Run the character-only gate before a bank scene:

```powershell
python tools/run_character_generation_test.py `
  --reference assets/characters/person-front.png `
  --reference assets/characters/person-side.png `
  --reference assets/characters/person-3quarter.png `
  --reference assets/characters/person-full-body.png
```

The test always writes
`output/character_generation_test/character_quality_report.json`. With no provider it
stops with `Production 3D character provider is not configured.` It does not create fake
beauty renders. Blender rejects models without production-level mesh density, plausible
bounds, UVs, textures, multiple materials, a recognizable humanoid skeleton, and facial
bones or shape keys. Animation and the bank scene remain blocked until that report passes.

Supported formats are `16:9`, `9:16`, and `1:1`.

Open the real production editor after a project has a storyboard:

```text
http://localhost:8000/api/projects/<project_id>/editor
```

The editor reads and modifies the real timeline, renders animated previews, and
supports component-specific background, character, voice, SFX, camera,
expression, animation, and scene regeneration. API consumers can use:

```text
GET   /api/projects/<id>/production-plan
PATCH /api/projects/<id>/scenes/<scene_id>
POST  /api/projects/<id>/scenes/<scene_id>/preview?quality=PREVIEW
POST  /api/projects/<id>/scenes/<scene_id>/regenerate/<component>
```

Render the deterministic 10-second forest acceptance scene with:

```bash
python tools/render_forest_animation_test.py
```

---

## YouTube setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **YouTube Data API v3**
3. Create **OAuth 2.0 credentials** (Desktop app)
4. Set `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` in `.env`
5. Run any upload command — a browser window will open for the one-time OAuth flow
6. The refresh token is saved to `projects/youtube_token.json` automatically

All uploads default to **private**. Use `python -m app.main publish --project <id>` after reviewing.

---

## Running tests

```bash
pip install pytest
python -m pytest tests/ -q
# Expected: ~123 passed, 2 skipped
```

The 2 skipped tests require `gtts` to be installed:
```bash
pip install gtts
python -m pytest tests/ -q
# Expected: 125 passed
```

---

## Docker

```bash
docker compose up --build
```

The container starts the FastAPI server. The scheduler can be enabled via environment variable:

```env
SCHEDULER_ENABLED=true
```

---

## Development phases

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ Complete | Topic → Research → Script (LLM pipeline) |
| 2 | ✅ Complete | SEO + Thumbnail + YouTube upload |
| 3 | ✅ Complete | Multi-agent architecture |
| 4 | ✅ Complete | Storyboard + Image generation (Pollinations) |
| 5 | ✅ Complete | TTS + FFmpeg video compositor |
| 6 | ✅ Complete | Autonomous scheduler (APScheduler, 3-day interval) |
| 7 | 🔄 In progress | FastAPI routes for agent pipeline (`/api/jobs`) |
| 8 | 📋 Planned | Web dashboard for human approval workflow |

---

## License

MIT — see [LICENSE](LICENSE) for details.

> **Important:** This system is designed for ethical, original content creation.
> It does not scrape, copy, or republish third-party content.
> Always review generated content before publishing.
> Never use it to upload misleading, infringing, or policy-violating content.
# Character Studio webpage

The easiest way to generate a character is to double-click:

```text
start_character_studio.bat
```

It checks/starts the local ComfyUI image generator, starts the web application,
and opens `http://127.0.0.1:8000/character-studio` in your browser. Enter a name
and detailed character description, choose **Master image** or **Full character
set**, and click **Generate character**. Every run gets a separate folder under:

```text
D:\AI_VIDEO_GENERATOR\character_library
```

The page shows live progress and previews. Use **Open folder** when generation
finishes. Keep the Character Studio command window open while using the page;
press `Ctrl+C` in that window to stop the web server.

## Cinematic audio milestone

The project now creates a shot-synchronized `audio_plan.json` before voice
generation. See [docs/audio_architecture.md](docs/audio_architecture.md) for the
VoicePack, local Piper, speech-markup, pronunciation, versioning, test-scene and
dependency-gate workflow.
