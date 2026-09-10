"""Production illustrated-asset preparation, segmentation, and quality gates.

Primitive drawing belongs to DEBUG rendering. DRAFT and PRODUCTION consume
cached or provider-generated raster artwork prepared by this module.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageStat


@dataclass(frozen=True)
class ArtDirection:
    style: str = "cinematic_2d_illustration"
    character_detail: str = "high"
    anatomy: str = "natural"
    texture: str = "painterly digital gouache with restrained paper grain"
    linework: str = "subtle hand-painted"
    environment_detail: str = "high"
    environment_depth: str = "layered"
    atmosphere: str = "cinematic"
    lighting: str = "directional moonlight, soft bounce, rim light, ambient occlusion"
    contrast: str = "medium_high"
    primary: str = "#12323a"
    secondary: str = "#526f68"
    accent: str = "#c58a49"
    shadow: str = "#050b10"
    highlight: str = "#b8d7dc"
    avoid: tuple[str, ...] = (
        "flat vector shapes", "geometric anatomy", "circle eyes", "stick limbs",
        "triangle trees", "3D render", "photorealism", "watermark",
    )


@dataclass
class AssetQualityReport:
    path: str
    asset_type: str
    passed: bool
    score: int
    checks: dict[str, bool]
    metrics: dict[str, float | int | str]
    problems: list[str] = field(default_factory=list)


class IllustratedAssetProvider(Protocol):
    """Provider-independent contract; adapters must declare real capabilities."""

    supports_reference_images: bool
    supports_transparency: bool

    def generate_character_reference(self, prompt: str, output_path: Path) -> Path: ...
    def generate_character_pose(self, prompt: str, reference: Path, output_path: Path) -> Path: ...
    def generate_character_expression(self, prompt: str, reference: Path, output_path: Path) -> Path: ...
    def generate_environment(self, prompt: str, output_path: Path) -> Path: ...
    def generate_prop(self, prompt: str, output_path: Path) -> Path: ...


class CachedIllustratedAssetProvider:
    """Development/offline provider that reuses accepted illustrated assets."""

    supports_reference_images = True
    supports_transparency = True

    def __init__(self, asset_root: Path) -> None:
        self.asset_root = asset_root

    def _copy(self, relative: str, output_path: Path) -> Path:
        source = self.asset_root / relative
        if not source.exists():
            raise FileNotFoundError(f"Cached illustrated asset unavailable: {source}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return output_path

    def generate_character_reference(self, prompt: str, output_path: Path) -> Path:
        return self._copy("characters/ravi/reference.png", output_path)

    def generate_character_pose(self, prompt: str, reference: Path, output_path: Path) -> Path:
        return self._copy("characters/ravi/reference.png", output_path)

    def generate_character_expression(self, prompt: str, reference: Path, output_path: Path) -> Path:
        return self._copy("characters/ravi/expressions/fear.png", output_path)

    def generate_environment(self, prompt: str, output_path: Path) -> Path:
        return self._copy("environment/forest_master.png", output_path)

    def generate_prop(self, prompt: str, output_path: Path) -> Path:
        raise NotImplementedError("The cached Forest Encounter provider has no prop asset")


def prepare_production_assets(
    environment_source: Path,
    character_source: Path,
    fear_source: Path,
    output_dir: Path,
    art_direction: ArtDirection | None = None,
) -> dict:
    """Validate, segment, layer, rig, and persist one coherent asset package."""
    direction = art_direction or ArtDirection()
    output_dir.mkdir(parents=True, exist_ok=True)
    environment_dir = output_dir / "environment"
    character_dir = output_dir / "characters" / "ravi"
    environment_dir.mkdir(parents=True, exist_ok=True)
    character_dir.mkdir(parents=True, exist_ok=True)

    master = environment_dir / "background.png"
    shutil.copy2(environment_source, master)
    reference = character_dir / "reference.png"
    shutil.copy2(character_source, reference)
    fear_cutout = character_dir / "expressions" / "fear.png"
    fear_cutout.parent.mkdir(parents=True, exist_ok=True)
    remove_subject_background(fear_source, fear_cutout)

    reports = [
        evaluate_asset(master, "environment"),
        evaluate_asset(reference, "character"),
        evaluate_asset(fear_cutout, "expression"),
    ]
    failed = [report for report in reports if not report.passed]
    if failed:
        raise ValueError(
            "Production asset quality gate rejected: "
            + "; ".join(f"{Path(item.path).name}: {', '.join(item.problems)}" for item in failed)
        )

    environment_layers = extract_environment_layers(master, environment_dir / "layers")
    rig_manifest = extract_character_rig(reference, character_dir / "rig")
    manifest: dict[str, Any] = {
        "asset_pipeline_version": 1,
        "visual_quality": "PRODUCTION",
        "art_direction": asdict(direction),
        "environment": {
            "master": str(master.resolve()),
            "layers": {key: str(value.resolve()) for key, value in environment_layers.items()},
        },
        "character": {
            "character_id": "ravi-forest-encounter",
            "reference": str(reference.resolve()),
            "rig_manifest": str(rig_manifest.resolve()),
            "expressions": {"fear": str(fear_cutout.resolve())},
        },
        "quality_reports": [asdict(report) for report in reports],
    }
    manifest_path = output_dir / "asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**manifest, "manifest_path": str(manifest_path.resolve())}


def evaluate_asset(path: Path, asset_type: str) -> AssetQualityReport:
    image = Image.open(path)
    rgb = image.convert("RGB")
    width, height = image.size
    alpha_coverage = 1.0
    has_transparency = False
    # Detail is measured on the subject itself, not diluted by a cut-out
    # transparent background: a cleanly segmented character crop should not
    # score as "low detail" just because most of the canvas is now empty.
    stats_source = rgb
    subject_bbox: tuple[int, int, int, int] | None = None
    if "A" in image.mode:
        alpha = image.getchannel("A")
        histogram = alpha.histogram()
        total = width * height
        transparent = sum(histogram[:16])
        alpha_coverage = round(1.0 - transparent / max(total, 1), 4)
        has_transparency = transparent > total * 0.03
        if has_transparency:
            subject_bbox = alpha.point(lambda v: 255 if v > 16 else 0).getbbox()
            if subject_bbox:
                stats_source = rgb.crop(subject_bbox)
    grayscale = stats_source.convert("L")
    entropy = round(grayscale.entropy(), 3)
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    edge_mean = round(ImageStat.Stat(edges).mean[0], 3)
    colors = stats_source.resize((256, 256), Image.Resampling.BILINEAR).quantize(colors=256).getcolors()
    unique_colors = len(colors or [])

    diagram_types = {
        "animated-map", "newspaper-document", "evidence-board", "date-card",
        "location-card", "diagram",
    }
    # Scene backgrounds for the master-timeline reconstruction pipeline are
    # deliberately rendered at 768x432 (app/agents/asset_agent.py's _comfyui
    # and _pollinations both hardcode this) - it's the compositing resolution
    # animated_renderer.py works at before ffmpeg upscales to final output;
    # it is not a defect to be measured against near-final-resolution assets.
    reconstruction_types = {"cinematic-reenactment"}
    is_diagram = asset_type in diagram_types
    is_reconstruction = asset_type in reconstruction_types
    if is_diagram:
        min_width, min_height, entropy_floor, edge_floor, color_floor = 1280, 720, 3.5, 2.0, 48
    elif is_reconstruction:
        min_width, min_height, entropy_floor, edge_floor, color_floor = 760, 420, 4.5, 3.5, 96
    else:
        min_width, min_height, entropy_floor, edge_floor, color_floor = 1000, 900, 5.0, 5.0, 128
    checks = {
        "resolution": width >= min_width and height >= min_height,
        # Maps/cards intentionally contain quiet negative space and clean lines;
        # applying painterly-environment thresholds rejects valid editorial art.
        "detail_entropy": entropy >= entropy_floor,
        "edge_detail": edge_mean >= edge_floor,
        "color_complexity": unique_colors >= color_floor,
        "transparency": True,
    }
    if asset_type in {"character", "expression"}:
        checks["transparency"] = has_transparency and 0.12 <= alpha_coverage <= 0.88
    weights = {
        "resolution": 20, "detail_entropy": 25, "edge_detail": 20,
        "color_complexity": 20, "transparency": 15,
    }
    if asset_type == "character" and subject_bbox:
        # A generation provider ignoring "plain background" instructions (a
        # painted room, a poster propped against a wall, ...) can still
        # segment out a plausible-looking subject region that isn't a clean
        # standing figure, so alpha_coverage alone can still land in the
        # accepted range while the alpha bbox is nowhere near a standing
        # human silhouette. app.images.character_illustration's
        # rig extraction assumes standing-figure proportions (head in the top
        # ~20%, legs in the bottom ~40%) and produces visibly torn, misplaced
        # body parts when fed a bbox like a near-square prop-and-wall scene.
        # Weighted so failing it alone caps the score below the passing
        # threshold regardless of every other check - this is a hard
        # prerequisite for rig extraction, not a soft quality signal.
        bbox_w = subject_bbox[2] - subject_bbox[0]
        bbox_h = subject_bbox[3] - subject_bbox[1]
        checks["silhouette_shape"] = 0.15 <= (bbox_w / max(bbox_h, 1)) <= 0.65
        weights = {name: round(value * 0.75) for name, value in weights.items()}
        weights["silhouette_shape"] = 25
    score = sum(weights[name] for name, passed in checks.items() if passed)
    problems = [name for name, passed in checks.items() if not passed]
    return AssetQualityReport(
        path=str(path.resolve()), asset_type=asset_type, passed=score >= 80,
        score=score, checks=checks,
        metrics={
            "width": width, "height": height, "mode": image.mode,
            "entropy": entropy, "edge_mean": edge_mean,
            "unique_colors_256": unique_colors, "alpha_coverage": alpha_coverage,
        },
        problems=problems,
    )


_rembg_session_cache: dict[str, Any] = {}


def _rembg_session():
    """Lazily load and cache the human-segmentation model (one ~176MB
    download on first use, then instant from the local rembg cache)."""
    session = _rembg_session_cache.get("session")
    if session is None:
        from rembg import new_session

        session = new_session("u2net_human_seg")
        _rembg_session_cache["session"] = session
    return session


def remove_subject_background(source_path: Path, output_path: Path) -> Path:
    """Isolate the illustrated subject with a trained human-segmentation model.

    A brightness/connected-component heuristic previously did this job but
    could not distinguish a light-toned garment from a light studio backdrop
    - it silently erased large parts of any white/cream shirt, saree, kurta,
    or achkan (common in real historical-figure references), leaving a torn
    silhouette or a giant erased halo around the whole figure. A trained
    segmentation model has no such blind spot: it identifies the person as a
    subject regardless of how their clothing's color relates to the backdrop.
    """
    source = Image.open(source_path).convert("RGB")
    pixels = np.asarray(source, dtype=np.uint8)
    border = np.concatenate((pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]))
    neutral_bright = ((border.max(axis=1)-border.min(axis=1) <= 18)
                      & (border.min(axis=1) >= 214))
    if float(neutral_bright.mean()) >= .80:
        # Studio white/checker backgrounds have a safe deterministic fast path.
        spread = pixels.max(axis=2).astype(np.int16)-pixels.min(axis=2).astype(np.int16)
        candidate = ((spread <= 18) & (pixels.min(axis=2) >= 214)).astype(np.uint8)
        count, labels = cv2.connectedComponents(candidate, connectivity=8)
        edge_labels = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
        background = np.isin(labels, edge_labels[edge_labels != 0]) if count > 1 else np.zeros(labels.shape, bool)
        result = source.convert("RGBA")
        result.putalpha(Image.fromarray(np.where(background, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.1)))
    else:
        from rembg import remove
        result = remove(source, session=_rembg_session())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path, "PNG", compress_level=1)
    return output_path


def extract_environment_layers(master_path: Path, output_dir: Path) -> dict[str, Path]:
    """Create coherent parallax mattes from one approved illustrated plate."""
    image = Image.open(master_path).convert("RGBA")
    width, height = image.size
    output_dir.mkdir(parents=True, exist_ok=True)
    layers: dict[str, Path] = {}

    # Distant artwork is a softened, slightly desaturated copy used beneath the
    # master crop when the camera shifts beyond its safe edge.
    distant = ImageEnhanceCompat.color(image, 0.78).filter(ImageFilter.GaussianBlur(1.4))
    distant_path = output_dir / "distant.png"
    distant.save(distant_path, "PNG", optimize=True)
    layers["distant"] = distant_path

    vertical = Image.linear_gradient("L").resize(image.size, Image.Resampling.BILINEAR)
    horizontal = Image.linear_gradient("L").rotate(90, expand=True).resize(image.size, Image.Resampling.BILINEAR)
    edge = horizontal.point(lambda value: min(255, abs(value - 128) * 2))
    mattes = {
        "midground": ImageChops.multiply(
            vertical.point(lambda value: round(255 * _smoothstep(0.38, 0.76, value / 255))),
            edge.point(lambda value: 255 - round(value * 0.45)),
        ),
        "foreground": ImageChops.lighter(
            vertical.point(lambda value: round(255 * _smoothstep(0.67, 0.94, value / 255))),
            edge.point(lambda value: round(255 * _smoothstep(0.64, 0.98, value / 255))),
        ),
    }
    source_alpha = image.getchannel("A")
    for name, matte in mattes.items():
        alpha = ImageChops.multiply(source_alpha, matte)
        layer = image.copy()
        layer.putalpha(alpha.filter(ImageFilter.GaussianBlur(max(2, width // 500))))
        path = output_dir / f"{name}.png"
        layer.save(path, "PNG", optimize=True)
        layers[name] = path
    return layers


def extract_character_rig(reference_path: Path, output_dir: Path) -> Path:
    """Partition approved artwork into a hierarchical, transformable cutout rig.

    This is deliberately an artwork segmentation operation: every visible pixel
    comes from ``reference_path``.  The returned joint graph is consumed by the
    articulated renderer; a monolithic character-position track is not a rig.
    The automatic masks are deterministic and may be replaced by same-named
    hand-corrected PNGs before a production render.
    """
    source = Image.open(reference_path).convert("RGBA")
    alpha = source.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        raise ValueError("Character reference has no visible pixels")
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    output_dir.mkdir(parents=True, exist_ok=True)

    part_names = (
        "head", "neck", "torso", "clothing",
        "hair", "eyes", "eyebrows", "mouth",
        "left_upper_arm", "left_lower_arm", "left_hand",
        "right_upper_arm", "right_lower_arm", "right_hand",
        "left_upper_leg", "left_lower_leg", "left_foot",
        "right_upper_leg", "right_lower_leg", "right_foot",
    )
    # Classify only the occupied crop with vectorized normalized coordinates.
    # The previous per-pixel Python loop made a normal 1K character take tens
    # of seconds before rendering had even begun.
    alpha_array = np.asarray(alpha, dtype=np.uint8)
    labels = np.empty((height, width), dtype=np.uint8)
    yy, xx = np.mgrid[0:height, 0:width]
    nx = xx / max(width, 1)
    ny = yy / max(height, 1)
    labels[:] = part_names.index("torso")
    labels[ny < 0.205] = part_names.index("head")
    labels[(ny >= 0.205) & (ny < 0.255) & (nx >= .43) & (nx <= .57)] = part_names.index("neck")
    leg = ny > 0.59
    left_side = nx < 0.52
    labels[leg & left_side & (ny <= 0.76)] = part_names.index("left_upper_leg")
    labels[leg & left_side & (ny > 0.76) & (ny <= 0.90)] = part_names.index("left_lower_leg")
    labels[leg & left_side & (ny > 0.90)] = part_names.index("left_foot")
    labels[leg & ~left_side & (ny <= 0.76)] = part_names.index("right_upper_leg")
    labels[leg & ~left_side & (ny > 0.76) & (ny <= 0.90)] = part_names.index("right_lower_leg")
    labels[leg & ~left_side & (ny > 0.90)] = part_names.index("right_foot")
    upper = (ny >= 0.205) & (ny <= 0.59)
    labels[upper & (nx < 0.34) & (ny <= 0.40)] = part_names.index("left_upper_arm")
    labels[upper & (nx < 0.34) & (ny > 0.40) & (ny <= 0.54)] = part_names.index("left_lower_arm")
    labels[upper & (nx < 0.34) & (ny > 0.54)] = part_names.index("left_hand")
    labels[upper & (nx > 0.70) & (ny <= 0.40)] = part_names.index("right_upper_arm")
    labels[upper & (nx > 0.70) & (ny > 0.40) & (ny <= 0.54)] = part_names.index("right_lower_arm")
    labels[upper & (nx > 0.70) & (ny > 0.54)] = part_names.index("right_hand")
    # Facial and clothing controls are retained as independently addressable
    # painted layers.  They are small source-derived masks, never replacement
    # geometry.  Clothing remains on the torso in the beauty render; its layer
    # is provided for manual correction/secondary motion and hidden by default.
    face_regions = {
        "hair": (0.39, 0.0, 0.61, 0.065),
        "eyes": (0.405, 0.075, 0.595, 0.122),
        "eyebrows": (0.415, 0.065, 0.585, 0.095),
        "mouth": (0.455, 0.145, 0.545, 0.178),
    }
    for name, (x0, y0, x1, y1) in face_regions.items():
        region = (nx >= x0) & (nx <= x1) & (ny >= y0) & (ny <= y1)
        labels[region] = part_names.index(name)
    masks = {}
    crop_alpha = alpha_array[top:bottom, left:right]
    for index, name in enumerate(part_names):
        crop_mask = np.where(labels == index, crop_alpha, 0).astype(np.uint8)
        full_mask = np.zeros_like(alpha_array)
        full_mask[top:bottom, left:right] = crop_mask
        masks[name] = Image.fromarray(full_mask)

    pivot_norm = {
        "head": (0.50, 0.90), "neck": (0.50, 0.82),
        "torso": (0.50, 0.56), "clothing": (0.50, 0.50),
        "hair": (0.50, 0.90), "eyes": (0.50, 0.50),
        "eyebrows": (0.50, 0.50), "mouth": (0.50, 0.50),
        "left_upper_arm": (0.86, 0.10), "left_lower_arm": (0.60, 0.08),
        "left_hand": (0.55, 0.08), "right_upper_arm": (0.14, 0.10),
        "right_lower_arm": (0.40, 0.08), "right_hand": (0.45, 0.08),
        "left_upper_leg": (0.70, 0.06), "left_lower_leg": (0.58, 0.06),
        "left_foot": (0.55, 0.08), "right_upper_leg": (0.30, 0.06),
        "right_lower_leg": (0.42, 0.06), "right_foot": (0.45, 0.08),
    }
    # Joint coordinates are normalized within the occupied source bbox.  The
    # left/right labels describe the viewer-facing artwork, matching filenames.
    joint_norm = {
        "hips": (.50, .565), "spine": (.50, .40), "chest": (.50, .275),
        "neck": (.50, .215), "head": (.50, .185), "hair": (.50, .045),
        "eyes": (.50, .105), "eyebrows": (.50, .082), "mouth": (.50, .162),
        "shoulder_l": (.355, .275), "elbow_l": (.300, .425), "wrist_l": (.265, .555),
        "shoulder_r": (.645, .275), "elbow_r": (.700, .425), "wrist_r": (.735, .555),
        "hip_l": (.445, .565), "knee_l": (.425, .755), "ankle_l": (.405, .905), "toe_l": (.345, .955),
        "hip_r": (.555, .565), "knee_r": (.575, .755), "ankle_r": (.595, .905), "toe_r": (.655, .955),
    }
    joints = {
        name: [left + px * width, top + py * height]
        for name, (px, py) in joint_norm.items()
    }
    parents = {
        "torso": None, "clothing": "torso", "neck": "torso", "head": "neck",
        "hair": "head", "eyes": "head", "eyebrows": "head", "mouth": "head",
        "left_upper_arm": "torso", "left_lower_arm": "left_upper_arm", "left_hand": "left_lower_arm",
        "right_upper_arm": "torso", "right_lower_arm": "right_upper_arm", "right_hand": "right_lower_arm",
        "left_upper_leg": "torso", "left_lower_leg": "left_upper_leg", "left_foot": "left_lower_leg",
        "right_upper_leg": "torso", "right_lower_leg": "right_upper_leg", "right_foot": "right_lower_leg",
    }
    joint_for_part = {
        "torso": "hips", "clothing": "hips", "neck": "chest", "head": "neck",
        "hair": "head", "eyes": "head", "eyebrows": "head", "mouth": "head",
        "left_upper_arm": "shoulder_l", "left_lower_arm": "elbow_l", "left_hand": "wrist_l",
        "right_upper_arm": "shoulder_r", "right_lower_arm": "elbow_r", "right_hand": "wrist_r",
        "left_upper_leg": "hip_l", "left_lower_leg": "knee_l", "left_foot": "ankle_l",
        "right_upper_leg": "hip_r", "right_lower_leg": "knee_r", "right_foot": "ankle_r",
    }
    manifest: dict[str, Any] = {
        "rig_version": 3,
        "canvas_size": list(source.size),
        "source_bbox": list(bbox),
        "source_path": str(reference_path.resolve()),
        "representation": "segmented_artwork_skeleton",
        "manual_correction_supported": True,
        "joints": joints,
        "parents": parents,
        "parts": {},
    }
    for name, mask in masks.items():
        # Slight overlap hides cut seams during restrained joint rotation while
        # retaining the source illustration's outer alpha silhouette.
        # A small overlap supports manual cutout correction. Beauty rendering
        # uses continuous skeletal skinning, so expensive giant dilations are
        # unnecessary and previously made segmentation look stalled.
        dilated = cv2.dilate(np.asarray(mask), np.ones((7, 7), np.uint8), iterations=1)
        mask = ImageChops.darker(Image.fromarray(dilated), alpha)
        part_bbox = mask.getbbox()
        if not part_bbox:
            continue
        layer = source.copy()
        layer.putalpha(mask)
        cropped = layer.crop(part_bbox)
        path = output_dir / f"{name}.png"
        # Rig layers are intermediates; expensive maximum PNG optimization was
        # making this stage appear hung on normal 1K character sheets.
        cropped.save(path, "PNG", compress_level=1)
        manifest["parts"][name] = {
            "path": str(path.resolve()),
            "position": [part_bbox[0], part_bbox[1]],
            "size": [part_bbox[2] - part_bbox[0], part_bbox[3] - part_bbox[1]],
            "pivot": list(pivot_norm[name]),
            "joint": joint_for_part[name],
            "parent": parents[name],
            "visible": name != "clothing",
        }
    manifest_path = output_dir / "rig.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


class ImageEnhanceCompat:
    @staticmethod
    def color(image: Image.Image, amount: float) -> Image.Image:
        from PIL import ImageEnhance
        return ImageEnhance.Color(image).enhance(amount)


def _smoothstep(start: float, end: float, value: float) -> float:
    x = max(0.0, min(1.0, (value - start) / max(end - start, 1e-6)))
    return x * x * (3 - 2 * x)
