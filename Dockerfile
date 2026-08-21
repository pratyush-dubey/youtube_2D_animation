FROM python:3.11-slim

# ── System dependencies ────────────────────────────────────────────────────────
# FFmpeg: video/audio composition
# espeak-ng: pyttsx3 offline TTS fallback
# fonts-dejavu: subtitle rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    fonts-dejavu-core \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies ────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        google-genai>=1.0 \
        gtts>=2.5 \
        apscheduler>=3.10 \
        fastapi>=0.111 \
        uvicorn[standard]>=0.30

# ── Application code ───────────────────────────────────────────────────────────
COPY . .

# ── Runtime directories ────────────────────────────────────────────────────────
RUN mkdir -p output projects assets/music assets/sfx assets/fonts prompts/v1

# ── Non-root user ──────────────────────────────────────────────────────────────
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# ── Healthcheck ────────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Ports ──────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Default: start FastAPI server ─────────────────────────────────────────────
# Override for CLI: docker run ... python -m app.main create --topic "..."
CMD ["uvicorn", "app.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
