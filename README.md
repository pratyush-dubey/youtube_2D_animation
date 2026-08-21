# AI YouTube Automation

Automated 2D YouTube video generation system.

**Topic → Research → Script → Storyboard → Images → Voice → Music → Video → Thumbnail → SEO → YouTube Upload**

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
IMAGE_PROVIDER=pollinations    # pollinations | stability | placeholder
STABILITY_API_KEY=             # optional

# TTS
TTS_PROVIDER=gtts              # gtts | elevenlabs | pyttsx3
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
