"""
AssetAgent — generates 2D images for every scene.

Provider priority (resolved from IMAGE_PROVIDER setting):
  gemini       — Google Imagen 3 (best quality, uses same GEMINI_API_KEY)
  stability    — Stability AI REST API (credits-based)
  pollinations — Free cloud API, no key needed (enhance=false to keep prompt intact)
  placeholder  — Instant fallback, no API required

Character consistency:
  If context.character_sheet is populated (by CharacterAgent), each scene's
  image_prompt is automatically prefixed with the visual descriptions of any
  characters mentioned in that scene's narration/visual_description.

Image size: 1920×1080 JPEG for each scene.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import structlog

from app.agents.base import Agent, AgentContext
from app.config.settings import settings

logger = structlog.get_logger(__name__)


class AssetAgent(Agent):
    name = "asset_agent"
    max_retries = 1

    def _execute(self, context: AgentContext) -> dict[int, Path]:
        if not context.storyboard:
            raise ValueError("StoryboardAgent must run before AssetAgent")

        images_dir = context.output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        generated: dict[int, Path] = {}

        # Build a lookup: character/setting name → visual string
        char_visuals = _build_char_lookup(context.character_sheet)

        for scene in context.storyboard:
            scene_id = scene["scene_id"]
            img_path = images_dir / f"scene_{scene_id:03d}.jpg"

            # Resume — skip already generated
            if img_path.exists() and img_path.stat().st_size > 1000:
                generated[scene_id] = img_path
                continue

            prompt = scene.get("image_prompt", "")
            if not prompt:
                prompt = f"2D flat illustration for: {scene.get('visual_description', '')}"

            # Anchor to topic so the model doesn't drift on niche subjects
            topic = getattr(context, "chosen_topic", None) or getattr(context, "topic", "")
            if topic and topic.lower() not in prompt.lower():
                prompt = f"{topic} — {prompt}"

            # Inject character visual descriptions for any character mentioned
            # in this scene's narration or visual description
            scene_text = (
                scene.get("narration", "") + " " + scene.get("visual_description", "")
            ).lower()
            char_hints = [
                vis for name, vis in char_visuals.items()
                if name.lower() in scene_text
            ]
            if char_hints:
                prompt = prompt + ". Character refs: " + "; ".join(char_hints)

            path = self._generate_image(prompt, img_path, scene_id)
            generated[scene_id] = path

        context.images = generated
        logger.info(
            "assets_complete",
            project=context.project_id,
            images=len(generated),
        )
        return generated

    # ── provider dispatch ──────────────────────────────────────────────────

    def _generate_image(self, prompt: str, output_path: Path, scene_id: int) -> Path:
        provider = settings.image_provider.lower()

        if provider == "gemini":
            try:
                return self._gemini_imagen(prompt, output_path, scene_id)
            except Exception as exc:
                logger.warning("gemini_imagen_failed", scene=scene_id, error=str(exc))
                # Fall through to Pollinations

        if provider == "stability":
            stability_key = settings.stability_api_key
            if stability_key:
                try:
                    return self._stability_ai(prompt, output_path, stability_key)
                except Exception as exc:
                    logger.warning("stability_failed", scene=scene_id, error=str(exc))

        if provider in ("pollinations", "gemini", "stability"):
            # Pollinations is the universal free fallback
            try:
                return self._pollinations(prompt, output_path, scene_id)
            except Exception as exc:
                logger.warning("pollinations_failed", scene=scene_id, error=str(exc))

        # Final fallback — colored placeholder
        return self._placeholder(prompt, output_path, scene_id)

    # ── Gemini Imagen 3 ───────────────────────────────────────────────────

    def _gemini_imagen(self, prompt: str, output_path: Path, scene_id: int) -> Path:
        from app.images.gemini_provider import GeminiImagenProvider
        return GeminiImagenProvider().generate(prompt, output_path, seed=scene_id)

    # ── Stability AI ──────────────────────────────────────────────────────

    def _stability_ai(self, prompt: str, output_path: Path, api_key: str) -> Path:
        import json as _json
        payload = _json.dumps({
            "prompt": prompt[:1000],
            "aspect_ratio": "16:9",
            "output_format": "jpeg",
        }).encode()
        req = urllib.request.Request(
            "https://api.stability.ai/v2beta/stable-image/generate/core",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "image/*",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            output_path.write_bytes(resp.read())
        return output_path

    # ── Pollinations (free fallback) ──────────────────────────────────────

    def _pollinations(self, prompt: str, output_path: Path, scene_id: int = 0) -> Path:
        import urllib.parse
        # enhance=false: prevent Pollinations from rewriting the prompt with its
        # own LLM, which replaces specific subjects with generic imagery.
        safe = urllib.parse.quote(prompt[:800])
        seed = scene_id if scene_id > 0 else 42
        url = (
            f"https://image.pollinations.ai/prompt/{safe}"
            f"?width=1920&height=1080&model=flux&nologo=true&enhance=false&seed={seed}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "AIYouTubeBot/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) < 500:
            raise ValueError("Pollinations returned empty image")
        output_path.write_bytes(data)
        return output_path

    # ── Placeholder ───────────────────────────────────────────────────────

    def _placeholder(self, prompt: str, output_path: Path, scene_id: int) -> Path:
        try:
            from PIL import Image, ImageDraw
            colors = [
                "#1a1a2e", "#16213e", "#0f3460", "#533483",
                "#2d6a4f", "#1b4332", "#264653", "#2a9d8f",
            ]
            bg = colors[scene_id % len(colors)]
            r = int(bg[1:3], 16)
            g = int(bg[3:5], 16)
            b = int(bg[5:7], 16)
            img = Image.new("RGB", (1920, 1080), color=(r, g, b))
            draw = ImageDraw.Draw(img)
            draw.text((100, 100), f"Scene {scene_id}", fill=(255, 255, 255))
            draw.text((100, 160), prompt[:80], fill=(200, 200, 200))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(output_path), "JPEG", quality=85)
        except ImportError:
            output_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 1000)
        return output_path


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_char_lookup(character_sheet: dict) -> dict[str, str]:
    """
    Return a flat dict of  name → visual_description  from the character sheet.
    Both first names and full names are indexed so partial matches work.
    """
    lookup: dict[str, str] = {}
    for entry in character_sheet.get("characters", []):
        name = entry.get("name", "").strip()
        visual = entry.get("visual", "").strip()
        if name and visual:
            lookup[name] = visual
            # Also index first name alone for natural-language matches
            first = name.split()[0]
            if first not in lookup:
                lookup[first] = visual
    for entry in character_sheet.get("settings", []):
        name = entry.get("name", "").strip()
        visual = entry.get("visual", "").strip()
        if name and visual:
            lookup[name] = visual
    return lookup
