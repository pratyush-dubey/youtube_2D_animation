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

import hashlib
import json
import urllib.request
from dataclasses import asdict
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
        manifest_path = images_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

        # Build a lookup: character/setting name → visual string
        char_visuals = _build_char_lookup(context.character_sheet)

        for scene in context.storyboard:
            scene_id = scene["scene_id"]
            img_path = images_dir / f"scene_{scene_id:03d}.jpg"

            # Resume — skip already generated
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
            character_references = _scene_character_references(
                context.character_sheet,
                scene_text,
                str(scene.get("character_name") or ""),
            )
            if scene.get("character_motion") and scene.get("character_name"):
                position = str(scene.get("character_position", "right"))
                prompt += (
                    f". Environment plate only, no people or human figures. Leave open "
                    f"foreground space on the {position} for a separately animated character"
                )
            elif char_hints:
                prompt = prompt + ". Character refs: " + "; ".join(char_hints)

            prompt = _production_prompt(
                prompt, context.style, scene.get("asset_type", "cinematic-reenactment")
            )
            reference_key = "|".join(
                f"{path}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
                for path in character_references if path.exists()
            )
            prompt_hash = hashlib.sha256(
                f"{prompt}|{reference_key}".encode()
            ).hexdigest()[:16]
            if (
                img_path.exists()
                and img_path.stat().st_size > 1000
                and manifest.get(str(scene_id)) == prompt_hash
            ):
                self._prepare_scene_asset(scene, img_path, images_dir, context.character_sheet)
                generated[scene_id] = img_path
                continue

            generation_references = (
                [] if scene.get("character_motion") else character_references
            )
            path = self._generate_image(
                prompt,
                img_path,
                scene_id,
                generation_references,
                visual_quality=str(scene.get("visual_quality") or "DEBUG"),
            )
            from app.images.editorial_compositor import enhance_structured_asset
            path = enhance_structured_asset(
                path, str(scene.get("asset_type", "cinematic-reenactment")), scene_id
            )
            self._prepare_scene_asset(scene, path, images_dir, context.character_sheet)
            generated[scene_id] = path
            manifest[str(scene_id)] = prompt_hash

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        context.images = generated
        logger.info(
            "assets_complete",
            project=context.project_id,
            images=len(generated),
        )
        return generated

    def _prepare_scene_asset(
        self,
        scene: dict,
        path: Path,
        images_dir: Path,
        character_sheet: dict,
    ) -> None:
        """Quality-check illustrated art and expose its renderable layers."""
        visual_quality = str(scene.get("visual_quality", "")).upper()
        if visual_quality not in {"DRAFT", "PRODUCTION"}:
            return

        from app.images.production_assets import evaluate_asset, extract_environment_layers

        quality = evaluate_asset(path, "environment")
        scene["asset_quality"] = [asdict(quality)]
        if visual_quality == "PRODUCTION" and not quality.passed:
            raise ValueError(
                f"Scene {scene.get('scene_id')} production artwork failed the quality gate: "
                + ", ".join(quality.problems)
            )

        layer_dir = images_dir / "layers" / f"scene_{int(scene['scene_id']):03d}"
        layers = extract_environment_layers(path, layer_dir)
        scene["environment_assets"] = {
            name: str(layer.resolve()) for name, layer in layers.items()
        }
        _attach_character_assets(scene, character_sheet)

    # ── provider dispatch ──────────────────────────────────────────────────

    def _generate_image(
        self, prompt: str, output_path: Path, scene_id: int,
        reference_images: list[Path] | None = None,
        visual_quality: str = "DEBUG",
    ) -> Path:
        provider = settings.image_provider.lower()

        if provider == "gemini":
            try:
                return self._gemini_imagen(
                    prompt, output_path, scene_id, reference_images or []
                )
            except Exception as exc:
                logger.warning("gemini_imagen_failed", scene=scene_id, error=str(exc))
                # Fall through to Pollinations

        if reference_images:
            # A text-only fallback may create the wrong person. Use the verified
            # portrait itself instead of fabricating an identity.
            from app.images.character_references import create_reference_scene
            return create_reference_scene(reference_images[0], output_path)

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
        if str(visual_quality).upper() != "DEBUG":
            raise RuntimeError(
                "Illustrated image generation failed and primitive fallback is disabled. "
                "Use a cached illustrated asset or render this scene in explicit DEBUG mode."
            )
        return self._placeholder(prompt, output_path, scene_id)

    # ── Gemini Imagen 3 ───────────────────────────────────────────────────

    def _gemini_imagen(
        self, prompt: str, output_path: Path, scene_id: int,
        reference_images: list[Path] | None = None,
    ) -> Path:
        from app.images.gemini_provider import GeminiImagenProvider
        return GeminiImagenProvider().generate(
            prompt, output_path, seed=scene_id,
            reference_images=reference_images or [],
        )

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

_STYLE_BIBLE = (
    "Premium cinematic 2.5D documentary frame, realistic painterly subjects, "
    "deep forest-green and near-black shadows, warm amber practical light, "
    "restrained crimson danger accents, tactile film grain and paper texture, "
    "high contrast chiaroscuro, 16:9 composition, foreground midground and "
    "background clearly separated for parallax, historically grounded details"
)

_NEGATIVE_PROMPT = (
    "No words, letters, captions, labels, logos, watermark, pseudo-text, UI, "
    "photorealism, 3D render, malformed anatomy, duplicated subjects, collage grid"
)

_ASSET_DIRECTIONS = {
    "cinematic-reenactment": (
        "cinematic reenactment, dramatic motivated lighting, shallow depth, "
        "human action frozen at a meaningful instant, faces natural and restrained"
    ),
    "archival-portrait": (
        "single archival portrait presentation, monochrome silver-gelatin texture, "
        "subtle torn paper edge, uncluttered evidence-table composition"
    ),
    "archival-footage": (
        "documentary archival footage still, period-accurate wardrobe and location, "
        "16mm grain, slightly imperfect exposure, no camera UI"
    ),
    "animated-map": (
        "dark topographic map, accurate land silhouette, one highlighted route or region, "
        "no place-name text, clean geographic hierarchy, subtle relief texture"
    ),
    "newspaper-document": (
        "investigative document close-up, blank article-like columns with no readable text, "
        "one amber highlight stroke, paper creases, overhead evidence-table lighting"
    ),
    "evidence-board": (
        "investigative evidence-board composition, photographs and document fragments, "
        "red thread accents, strong central clue, no readable text"
    ),
    "date-card": "minimal dark textured background with one central empty title-safe area",
    "location-card": "moody aerial establishing view with clean title-safe negative space",
    "diagram": "clean cinematic information diagram with icons and lines but no text or numbers",
    "atmospheric-detail": (
        "extreme close-up insert shot of one story-relevant object, tactile surface, "
        "dramatic rim light, strong visual tension"
    ),
}


def _production_prompt(prompt: str, style: str, asset_type: str) -> str:
    """Lock every image to one art direction and caption-safe composition."""
    requested_style = (style or "documentary").strip()
    asset_direction = _ASSET_DIRECTIONS.get(
        str(asset_type).lower(), _ASSET_DIRECTIONS["cinematic-reenactment"]
    )
    return (
        f"{_STYLE_BIBLE}. Visual system: {asset_direction}. Tone: {requested_style}. "
        f"Subject: {prompt.strip()}. "
        "Keep the main subject inside the central 70 percent safe area and leave "
        f"clean lower-third space for captions. {_NEGATIVE_PROMPT}."
    )


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


def _scene_character_references(
    character_sheet: dict, scene_text: str, explicit_name: str = ""
) -> list[Path]:
    references: list[Path] = []
    for entry in character_sheet.get("characters", []):
        name = str(entry.get("name", "")).strip()
        mentioned = bool(explicit_name and name.casefold() == explicit_name.casefold())
        mentioned = mentioned or bool(name and name.casefold() in scene_text.casefold())
        if not mentioned:
            continue
        status = str(entry.get("identity_reference_status", ""))
        path = Path(str(entry.get("reference_image", "")))
        if status.startswith("verified") and path.exists() and path not in references:
            references.append(path)
    return references


def _attach_character_assets(scene: dict, character_sheet: dict) -> None:
    """Attach accepted character rig metadata without inventing an identity."""
    requested = str(scene.get("character_name") or "").casefold()
    if not requested:
        return
    for entry in character_sheet.get("characters", []):
        if str(entry.get("name") or "").casefold() != requested:
            continue
        rig = Path(str(entry.get("rig_manifest") or ""))
        if rig.is_file():
            scene["character_rig_manifest"] = str(rig.resolve())
        expressions = {
            str(name): str(Path(str(path)).resolve())
            for name, path in (entry.get("expressions") or {}).items()
            if Path(str(path)).is_file()
        }
        if expressions:
            scene["character_expressions"] = expressions
        reference = Path(str(entry.get("illustrated_reference") or ""))
        if reference.is_file():
            scene["character_asset"] = str(reference.resolve())
        return
