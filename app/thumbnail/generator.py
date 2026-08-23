"""
Thumbnail generator — creates a 1280x720 YouTube thumbnail using Pillow.

Reads a concept from the LLM ThumbnailPlanner and composites:
  • Gradient or solid background
  • Large bold main text
  • Smaller sub-text
  • Optional accent bar

No external fonts required — falls back to Pillow's built-in font.
For production quality, drop a TTF into assets/fonts/ and it's auto-detected.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import structlog

from app.config.settings import settings
from app.cost.tracker import CostTracker
from app.database.session import get_session
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.seo.schemas import SEOMetadata

logger = structlog.get_logger(__name__)

THUMB_W, THUMB_H = 1280, 720

_PROMPT_PATH = settings.prompt_dir / "thumbnail_prompt.txt"
_FONT_DIR = settings.asset_dir / "fonts"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Design 3 YouTube thumbnail concepts for topic: {topic}, title: {title}. "
        "Return JSON with key 'concepts' (list) and 'best_concept_id'. "
        "Each concept has: background_color, main_text, sub_text, text_color, "
        "accent_color, ctr_score. Return ONLY valid JSON."
    )


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert #RRGGBB to (R, G, B)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return r, g, b


def _load_font(size: int):
    """Load best available font, fallback to Pillow default."""
    try:
        from PIL import ImageFont
        # Try common system/project fonts in order
        candidates = [
            _FONT_DIR / "Roboto-Bold.ttf",
            _FONT_DIR / "DejaVuSans-Bold.ttf",
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
        ]
        for path in candidates:
            if path.exists():
                return ImageFont.truetype(str(path), size)
        return ImageFont.load_default()
    except Exception:
        from PIL import ImageFont
        return ImageFont.load_default()


def _draw_gradient_bg(draw, width: int, height: int, color1: tuple, color2: tuple) -> None:
    """Draw a vertical gradient between two RGB colors."""
    for y in range(height):
        t = y / height
        r = int(color1[0] * (1 - t) + color2[0] * t)
        g = int(color1[1] * (1 - t) + color2[1] * t)
        b = int(color1[2] * (1 - t) + color2[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def _draw_accent_bar(draw, color: tuple, width: int, height: int) -> None:
    """Draw a left-side accent bar."""
    bar_w = max(12, width // 60)
    draw.rectangle([(0, 0), (bar_w, height)], fill=color)


def _wrap_text_lines(text: str, font, max_width: int, draw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        try:
            bbox = draw.textbbox((0, 0), test, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(test) * (font.size if hasattr(font, "size") else 10)
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def render_thumbnail(
    concept: dict[str, Any],
    output_path: Path,
) -> Path:
    """
    Render a single thumbnail concept to a JPEG file.
    Returns the output path.
    """
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageOps
    except ImportError as exc:
        raise ImportError("Pillow not installed. Run: pip install Pillow") from exc

    bg_color = concept.get("background_color", "#1a1a2e")
    bg2_color = concept.get("background_color_2", "#16213e")
    text_color = concept.get("text_color", "#ffffff")
    accent_color = concept.get("accent_color", "#ff6b35")
    main_text = concept.get("main_text", "").upper()
    sub_text = concept.get("sub_text") or ""

    img = Image.new("RGB", (THUMB_W, THUMB_H), color=_hex_to_rgb(bg_color))
    draw = ImageDraw.Draw(img)

    # Gradient background
    c1 = _hex_to_rgb(bg_color)
    c2 = _hex_to_rgb(bg2_color)
    _draw_gradient_bg(draw, THUMB_W, THUMB_H, c1, c2)

    background_image = Path(str(concept.get("background_image", "")))
    if background_image.is_file():
        plate = ImageOps.fit(Image.open(background_image).convert("RGB"), (THUMB_W, THUMB_H), Image.Resampling.LANCZOS)
        plate = ImageEnhance.Brightness(plate).enhance(0.48)
        img = Image.blend(img, plate, 0.66)
        draw = ImageDraw.Draw(img)

    # Accent bar on left
    _draw_accent_bar(draw, _hex_to_rgb(accent_color), THUMB_W, THUMB_H)

    focal_image = Path(str(concept.get("focal_image", "")))
    if focal_image.is_file():
        focal = Image.open(focal_image).convert("RGBA")
        bbox = focal.getchannel("A").getbbox()
        if bbox:
            focal = focal.crop(bbox)
            target_h = round(THUMB_H * 0.92)
            scale = target_h / focal.height
            focal = focal.resize((max(1, round(focal.width * scale)), target_h), Image.Resampling.LANCZOS)
            stage = img.convert("RGBA")
            stage.alpha_composite(focal, (THUMB_W - focal.width - 20, THUMB_H - focal.height))
            img = stage.convert("RGB")
            draw = ImageDraw.Draw(img)

    # Layout: text fills left 65%, right 35% reserved for focal image
    text_zone_w = int(THUMB_W * 0.62)
    margin = 60
    usable_w = text_zone_w - margin * 2

    # Main text — large bold
    main_font_size = 110
    main_font = _load_font(main_font_size)
    main_lines = _wrap_text_lines(main_text, main_font, usable_w, draw)

    # Calculate total height of main text block
    line_h = main_font_size + 10
    total_main_h = line_h * len(main_lines)

    # Sub text — smaller
    sub_font_size = 52
    sub_font = _load_font(sub_font_size)
    sub_lines = _wrap_text_lines(sub_text, sub_font, usable_w, draw) if sub_text else []
    total_sub_h = (sub_font_size + 8) * len(sub_lines) if sub_lines else 0

    gap = 24
    total_h = total_main_h + (gap + total_sub_h if sub_lines else 0)
    start_y = (THUMB_H - total_h) // 2

    # Draw shadow for main text
    for line in main_lines:
        draw.text((margin + 3, start_y + 3), line, font=main_font, fill=(0, 0, 0, 180))
        draw.text((margin, start_y), line, font=main_font, fill=_hex_to_rgb(text_color))
        start_y += line_h

    # Draw sub text
    if sub_lines:
        start_y += gap
        sub_color = _hex_to_rgb(accent_color)
        for line in sub_lines:
            draw.text((margin + 2, start_y + 2), line, font=sub_font, fill=(0, 0, 0, 140))
            draw.text((margin, start_y), line, font=sub_font, fill=sub_color)
            start_y += sub_font_size + 8

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "JPEG", quality=95, optimize=True)
    logger.info("thumbnail_rendered", path=str(output_path), w=THUMB_W, h=THUMB_H)
    return output_path


class ThumbnailGenerator:
    """
    Uses LLM to design thumbnail concepts then renders the best one with Pillow.
    """

    def __init__(
        self,
        project_id: str,
        llm: LLMProvider | None = None,
    ) -> None:
        self.project_id = project_id
        self.llm = llm or get_llm_provider()
        self.cost_tracker = CostTracker(project_id)

    def generate(
        self,
        topic: str,
        seo: SEOMetadata,
        output_dir: Path,
        style: str = "documentary",
    ) -> Path:
        """
        Plan thumbnail concepts via LLM, render the best one.
        Returns path to the rendered thumbnail JPEG.
        """
        thumb_path = output_dir / "thumbnail.jpg"

        # Resume — skip if already rendered
        if thumb_path.exists():
            logger.info("thumbnail_already_exists", project=self.project_id)
            return thumb_path

        logger.info("thumbnail_generation_started", project=self.project_id, topic=topic)

        # Get key visuals from topic
        key_visuals = f"{topic}, {seo.best_title}"

        prompt = (
            _load_prompt()
            .replace("{topic}", topic)
            .replace("{title}", seo.best_title)
            .replace("{style}", style)
            .replace("{key_visuals}", key_visuals)
        )

        try:
            raw, response = self.llm.generate_json(
                prompt,
                schema_hint="ThumbnailConcepts",
                temperature=0.8,
                # Three compact concepts fit comfortably below this ceiling.
                # The renderer already has a deterministic fallback, so one
                # bounded attempt is preferable to repeated multi-minute local
                # generations.
                max_tokens=1000,
                max_retries=1,
            )

            self.cost_tracker.record(
                provider=self.llm.provider_name,
                model=getattr(self.llm, "model", "unknown"),
                operation="thumbnail",
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )

            concepts = raw.get("concepts", [])
            best_id = raw.get("best_concept_id", 1)

            # Find the best concept
            best_concept = next(
                (c for c in concepts if c.get("id") == best_id),
                concepts[0] if concepts else None,
            )

        except Exception as exc:
            logger.warning(
                "thumbnail_llm_failed_using_fallback",
                project=self.project_id,
                error=str(exc),
            )
            best_concept = None

        # Use fallback concept if LLM failed or returned nothing
        if not best_concept:
            best_concept = _fallback_concept(topic, seo.best_title)

        render_thumbnail(best_concept, thumb_path)
        logger.info("thumbnail_complete", project=self.project_id, path=str(thumb_path))
        return thumb_path


def _fallback_concept(topic: str, title: str) -> dict[str, Any]:
    """Minimal fallback concept when LLM is unavailable."""
    words = title.split()
    main_text = " ".join(words[:4]) if len(words) >= 4 else title
    sub_text = " ".join(words[4:8]) if len(words) > 4 else topic[:30]
    return {
        "background_color": "#0d1117",
        "background_color_2": "#1a2332",
        "main_text": main_text,
        "sub_text": sub_text,
        "text_color": "#ffffff",
        "accent_color": "#3b82f6",
    }
