"""Turn a resolved character (reference photo or fictional bible) into a
riggable, alpha-transparent illustration.

This is the missing link between character identity (app/agents/character_agent.py,
app/images/character_references.py) and the skeletal renderer (app/video/illustrated_rig.py):
without an illustrated master and a rig manifest, animated_renderer.py has no
articulated character to render. app/agents/asset_agent.py._attach_character_assets
already reads entry["illustrated_reference"] / entry["rig_manifest"] / entry["expressions"]
off a character-sheet entry, so this module only needs to populate them.
"""
from __future__ import annotations

import re
from pathlib import Path

import structlog

from app.characters.provider import create_character_image_provider
from app.images.production_assets import evaluate_asset, extract_character_rig, remove_subject_background

logger = structlog.get_logger(__name__)

EXPRESSIONS = ("neutral", "happy", "fear", "surprised")


def _pollinations_attempts(entry: dict, style: str):
    """Ordered (name, generate_fn) attempts, best identity fidelity first.

    A reference-backed character (a real, researched person) gets exactly
    one Pollinations attempt: kontext image-to-image. Plain flux text-to-image
    has no reference input at all - for a real person it always invents a
    generic face, never the actual one, regardless of how detailed the text
    prompt is or how well the result scores on the (identity-blind) quality
    gate. Including flux as a fallback here would let that generic result
    count as "generated" and skip past the reference-aware local provider in
    illustrate_character(), which is the only remaining path that can
    actually honor the reference. A character with no reference (fictional)
    has no identity to preserve, so flux is its normal, sole fast path.
    """
    from app.images.pollinations_provider import PollinationsProvider

    provider = PollinationsProvider()
    public_url = str(entry.get("reference_public_url") or "")
    prompt = _master_prompt(entry, style)
    if public_url:
        return [(
            "kontext",
            lambda raw: provider.generate_image_to_image(prompt, public_url, raw, width=1024, height=1536),
        )]
    return [("flux", lambda raw: provider.generate_portrait(prompt, raw))]


def _generate_via_pollinations(entry: dict, style: str, raw_master: Path) -> bool:
    """Free, cloud-hosted first attempt: seconds, not CPU-bound minutes.

    Tries each candidate in order, keeping the first result that survives
    background removal and the quality gate.
    """
    for attempt_name, generate in _pollinations_attempts(entry, style):
        try:
            generate(raw_master)
        except Exception as exc:
            logger.warning(
                "character_illustration_pollinations_attempt_failed",
                character=entry.get("name"), attempt=attempt_name, error=str(exc)[:300],
            )
            continue
        if _passes_quality_gate(raw_master):
            return True
        logger.warning(
            "character_illustration_pollinations_attempt_rejected",
            character=entry.get("name"), attempt=attempt_name,
        )
    return False


def _passes_quality_gate(raw_master: Path) -> bool:
    """Preview the quality gate on a scratch copy without touching master.png."""
    scratch = raw_master.with_name(f"{raw_master.stem}_gatecheck.png")
    try:
        _ensure_min_resolution(raw_master, 1024, 1536)
        remove_subject_background(raw_master, scratch)
        return evaluate_asset(scratch, "character").passed
    finally:
        scratch.unlink(missing_ok=True)


def illustrate_character(entry: dict, output_dir: Path, style: str = "") -> dict:
    """Populate entry with illustrated_reference / rig_manifest / expressions.

    Idempotent across resumes: if a rig already exists on disk for this
    character it is reused rather than regenerated. Any failure (no provider
    configured, generation error, quality gate rejection) leaves entry
    unchanged so the caller falls back to today's behaviour rather than
    crashing character setup for an unrelated provider outage.
    """
    name = str(entry.get("name") or "").strip()
    character_id = str(entry.get("character_id") or name or "character")
    slug = _slug(character_id)
    char_dir = output_dir / "characters" / slug
    rig_path = char_dir / "rig" / "rig.json"
    master_path = char_dir / "master.png"

    if rig_path.is_file() and master_path.is_file():
        entry["illustrated_reference"] = str(master_path.resolve())
        entry["rig_manifest"] = str(rig_path.resolve())
        entry["expressions"] = _existing_expressions(char_dir)
        return entry

    char_dir.mkdir(parents=True, exist_ok=True)
    raw_master = char_dir / "master_raw.png"

    generated = _generate_via_pollinations(entry, style, raw_master)
    used_local_fallback = False
    if not generated:
        # Free/fast path failed (network outage, or every attempt missed the
        # quality gate) - fall back to whatever local provider is configured
        # (ComfyUI/A1111/imported), which is slower on CPU-only hardware but
        # keeps the pipeline from hard-failing.
        provider = create_character_image_provider()
        if not provider.configured:
            logger.warning("character_illustration_skipped", character=name, reason="no image provider configured")
            return entry
        reference = Path(str(entry.get("reference_image") or ""))
        prompt = _master_prompt(entry, style)
        try:
            if reference.is_file() and provider.supports_references:
                provider.generate_variation(prompt, reference, raw_master)
            else:
                provider.generate_master_character(prompt, raw_master)
            used_local_fallback = True
        except Exception as exc:
            logger.warning("character_illustration_failed", character=name, error=str(exc)[:300])
            return entry

    _ensure_min_resolution(raw_master, 1024, 1536)
    remove_subject_background(raw_master, master_path)
    report = evaluate_asset(master_path, "character")
    if not report.passed:
        # silhouette_shape is a hard prerequisite for rig extraction, not a
        # soft quality preference (see production_assets.py) - a provider
        # that ignored "plain background" and painted a whole room/prop scene
        # produces a rig with body parts sliced from wall/floor pixels, not a
        # merely-lower-quality one. Never use the best-effort override for it.
        if "silhouette_shape" in report.problems:
            logger.warning("character_illustration_rejected", character=name, problems=report.problems)
            return entry
        if not used_local_fallback or not _has_visible_content(master_path):
            logger.warning("character_illustration_rejected", character=name, problems=report.problems)
            return entry
        # Every generation strategy (kontext, flux, and local diffusion) has
        # now been tried and none cleared the strict gate. Rather than block
        # the whole video on one character's art quality, use the best
        # available result - a rig built from a slightly-below-threshold
        # illustration still animates; no rig at all hard-fails rendering.
        logger.warning(
            "character_illustration_using_below_threshold_result",
            character=name, problems=report.problems, score=report.score,
        )

    try:
        rig_manifest = extract_character_rig(master_path, char_dir / "rig")
    except Exception as exc:
        logger.warning("character_rig_extraction_failed", character=name, error=str(exc)[:300])
        return entry

    entry["illustrated_reference"] = str(master_path.resolve())
    entry["rig_manifest"] = str(rig_manifest.resolve())
    # Expression close-ups are NOT generated here: IllustratedCharacterRig loads
    # scene["character_expressions"] but never actually reads it during render
    # (expression is procedural via _pose()'s joint angles), so each one would
    # be a full extra diffusion call for zero visible effect. On CPU-only
    # inference (no CUDA build / no dedicated GPU) that is minutes of pure
    # waste per character. Re-enable via _generate_expressions() once the rig
    # actually swaps in per-expression art.
    entry["expressions"] = _existing_expressions(char_dir)
    return entry


def _generate_expressions(provider, entry: dict, master_path: Path, char_dir: Path, style: str) -> dict:
    """Not called by default; see the note in illustrate_character()."""
    expressions_dir = char_dir / "expressions"
    expressions_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for name in EXPRESSIONS:
        raw = expressions_dir / f"{name}_raw.png"
        cutout = expressions_dir / f"{name}.png"
        try:
            provider.generate_expression(_expression_prompt(entry, name, style), master_path, raw)
            remove_subject_background(raw, cutout)
            result[name] = str(cutout.resolve())
        except Exception as exc:
            logger.warning(
                "character_expression_failed", character=entry.get("name"), expression=name, error=str(exc)[:300]
            )
    return result


def _master_prompt(entry: dict, style: str, framing: str = "full-body, front view, neutral standing pose, entire body visible from head to shoes") -> str:
    name = entry.get("name") or "the character"
    appearance = str(entry.get("appearance") or entry.get("visual") or "").strip()
    clothing = str(entry.get("clothing") or "").strip()
    style_text = style.strip() or "painterly digital illustration, controlled outlines, natural anatomy"
    return (
        f"Cinematic 2D illustration of {name}, {framing}, hands visible at sides. {appearance} {clothing} "
        f"{style_text}. Solid pure white seamless background, studio cutout style, no shadow on background, "
        f"nothing else in the image except the person - no wall, no floor, no canvas, no poster, no picture frame, "
        f"no room, no props, no furniture. no text, no watermark."
    ).strip()


def _expression_prompt(entry: dict, expression: str, style: str) -> str:
    name = entry.get("name") or "the character"
    style_text = style.strip() or "painterly digital illustration, controlled outlines"
    return (
        f"Head-and-shoulders close-up of the same exact {name}, same outfit and hairstyle, "
        f"subtle {expression} expression, preserve facial geometry and identity. "
        f"{style_text}. Plain neutral flat background, no text."
    )


def _existing_expressions(char_dir: Path) -> dict:
    expressions_dir = char_dir / "expressions"
    if not expressions_dir.is_dir():
        return {}
    return {
        path.stem: str(path.resolve())
        for path in expressions_dir.glob("*.png")
        if not path.stem.endswith("_raw")
    }


def _has_visible_content(path: Path) -> bool:
    from PIL import Image

    with Image.open(path) as image:
        if "A" not in image.mode:
            return True
        return image.getchannel("A").getbbox() is not None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "character"


def _ensure_min_resolution(path: Path, min_width: int, min_height: int) -> None:
    """Upscale in place if below the floor; never downscale a larger source.

    Free cloud providers (Pollinations' anonymous tier) cap output at a fixed
    size regardless of the requested width/height. A local Lanczos upscale is
    instant and satisfies the pixel-count quality gate without another
    network round trip.
    """
    from PIL import Image

    with Image.open(path) as image:
        if image.width >= min_width and image.height >= min_height:
            return
        scale = max(min_width / image.width, min_height / image.height)
        size = (round(image.width * scale), round(image.height * scale))
        image.resize(size, Image.Resampling.LANCZOS).save(path)
