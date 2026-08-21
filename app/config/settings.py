"""
Central configuration via pydantic-settings.
All values are read from environment variables / .env file.
No API keys are ever hard-coded here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "production"
    app_name: str = "AI YouTube Automation"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    # ── Paths ──────────────────────────────────────────────────────────────
    output_dir: Path = Path("./output")
    asset_dir: Path = Path("./assets")
    project_dir: Path = Path("./projects")
    prompt_dir: Path = Path("./prompts/v1")
    db_path: Path = Path("./projects/db.sqlite3")

    # ── LLM Provider ───────────────────────────────────────────────────────
    # Default: gemini (generous free tier, cloud-hosted deployment)
    llm_provider: Literal["ollama", "openai", "gemini"] = "gemini"

    # Ollama (optional — local only, not needed for cloud-hosted deployment)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout: int = 120

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # Gemini (free tier: 15 RPM, 1 500 RPD — sufficient for 1 video/run)
    # Use the model name as shown by: client.models.list() (strip the "models/" prefix)
    # New accounts: gemini-3.6-flash  |  Older accounts: gemini-2.5-flash
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # LLM generation defaults
    llm_temperature: float = 0.7
    llm_max_tokens: int = 8192   # generous default; individual calls can override lower
    llm_max_retries: int = 5          # more attempts to handle 503 spikes
    llm_retry_delay: float = 5.0      # base delay; exponential backoff applied on top

    # ── Image Provider ─────────────────────────────────────────────────────
    # placeholder  — instant, no API, good for testing
    # pollinations — free cloud API (https://pollinations.ai), no key needed
    # stability    — Stability AI REST API, credits-based
    # gemini       — Google Imagen 3 via Gemini API (same key as LLM, best quality)
    image_provider: Literal[
        "placeholder", "stable_diffusion", "automatic1111", "pollinations", "stability", "gemini"
    ] = "pollinations"
    gemini_image_model: str = "gemini-3.1-flash-image"
    sd_model_id: str = "runwayml/stable-diffusion-v1-5"
    a1111_base_url: str = "http://localhost:7860"
    cinematic_image_provider: Literal[
        "unconfigured", "automatic1111", "gemini_image", "cached"
    ] = "unconfigured"
    zero_cost_mode: bool = True
    cinematic_debug: bool = False
    image_width: int = 1920
    image_height: int = 1080

    # Stability AI image generation (optional)
    stability_api_key: str = ""

    # Tavily search API (optional — improves research quality)
    tavily_api_key: str = ""

    # ── TTS Provider ───────────────────────────────────────────────────────
    # gtts      — Google Translate TTS (free, internet required, default)
    # elevenlabs— cloud TTS, free tier 10k chars/month, best quality
    # pyttsx3   — local offline fallback, lower quality
    # piper     — local MIT-license model (requires piper binary)
    # coqui     — local MPL2 model (heavier)
    tts_provider: Literal[
        "piper", "coqui", "edge_tts", "gtts", "elevenlabs", "pyttsx3"
    ] = "edge_tts"
    piper_model: str = "en_US-lessac-medium"
    piper_executable: str = "piper"
    tts_voice: str = "en-IN-PrabhatNeural"
    tts_speed: float = 1.10

    # ElevenLabs TTS (cloud, free tier 10k chars/month)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel — default voice

    # ── Video ──────────────────────────────────────────────────────────────
    # Set ffmpeg_path / ffprobe_path to an absolute path when ffmpeg is not
    # on the system PATH (common on Windows).  Leave empty to use PATH lookup.
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    blender_path: str = ""
    render_provider: Literal["cinematic_2d25d", "blender", "illustrated_2d"] = "cinematic_2d25d"
    art_style_preset: str = "CINEMATIC_ILLUSTRATED_DOCUMENTARY"
    character_3d_provider: Literal["blocked", "local", "mpfb"] = "blocked"
    local_character_model: str = ""
    character_3d_timeout_seconds: int = 900
    character_3d_poll_seconds: float = 5.0

    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_crf: int = 23  # 0-51; lower = better quality
    video_preset: str = "medium"
    render_quality: Literal["DRAFT", "PREVIEW", "FINAL"] = "FINAL"
    visual_quality: Literal["DEBUG", "DRAFT", "PRODUCTION"] = "PRODUCTION"
    allow_primitive_debug_assets: bool = False
    animation_quality_threshold: int = 70

    # ── Audio Mix Levels (dB) ──────────────────────────────────────────────
    narration_volume_db: float = -3.0
    music_volume_db: float = -24.0
    sfx_volume_db: float = -14.0
    music_duck_db: float = -18.0  # music level during narration

    # ── YouTube ────────────────────────────────────────────────────────────
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_token_file: Path = Path("./projects/youtube_token.json")
    youtube_privacy_status: Literal["private", "unlisted", "public"] = "private"
    auto_publish: bool = False
    youtube_category_id: str = "28"  # Science & Technology

    # ── Pipeline ───────────────────────────────────────────────────────────
    max_retries: int = 3
    retry_backoff_base: float = 2.0
    scene_padding_seconds: float = 0.25  # tight documentary beat between scenes
    words_per_minute: int = 130

    # ── Scheduler (APScheduler) ────────────────────────────────────────────
    # When enabled the scheduler fires every `scheduler_interval_days` days,
    # picks a trending topic in `scheduler_niche`, and runs the full pipeline.
    scheduler_enabled: bool = False
    scheduler_interval_days: int = 3
    scheduler_niche: str = "science and technology"
    scheduler_style: str = "documentary"
    scheduler_target_duration_seconds: int = 480

    # ── Content Safety ────────────────────────────────────────────────────
    content_safety_enabled: bool = True

    @field_validator("output_dir", "asset_dir", "project_dir", mode="after")
    @classmethod
    def _ensure_dirs(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v


# Module-level singleton — import this everywhere
settings = Settings()
