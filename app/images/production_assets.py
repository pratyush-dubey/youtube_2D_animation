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
    remove_connected_background(fear_source, fear_cutout)

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
    grayscale = rgb.convert("L")
    entropy = round(grayscale.entropy(), 3)
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    edge_mean = round(ImageStat.Stat(edges).mean[0], 3)
    colors = rgb.resize((256, 256), Image.Resampling.BILINEAR).quantize(colors=256).getcolors()
    unique_colors = len(colors or [])
    alpha_coverage = 1.0
    has_transparency = False
    if "A" in image.mode:
        alpha = image.getchannel("A")
        histogram = alpha.histogram()
        total = width * height
        transparent = sum(histogram[:16])
        alpha_coverage = round(1.0 - transparent / max(total, 1), 4)
        has_transparency = transparent > total * 0.03

    checks = {
        "resolution": width >= 1000 and height >= 900,
        "detail_entropy": entropy >= 5.0,
        "edge_detail": edge_mean >= 5.0,
        "color_complexity": unique_colors >= 128,
        "transparency": True,
    }
    if asset_type in {"character", "expression"}:
        checks["transparency"] = has_transparency and 0.12 <= alpha_coverage <= 0.88
    weights = {
        "resolution": 20, "detail_entropy": 25, "edge_detail": 20,
        "color_complexity": 20, "transparency": 15,
    }
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


def remove_connected_background(source_path: Path, output_path: Path) -> Path:
    """Remove a bright checker/neutral backdrop without erasing enclosed highlights."""
    source = Image.open(source_path).convert("RGB")
    width, height = source.size
    pixels = source.load()
    visited = bytearray(width * height)
    stack: list[tuple[int, int]] = []

    def candidate(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        return max(r, g, b) - min(r, g, b) <= 16 and min(r, g, b) >= 218

    for x in range(width):
        if candidate(x, 0):
            stack.append((x, 0))
        if candidate(x, height - 1):
            stack.append((x, height - 1))
    for y in range(height):
        if candidate(0, y):
            stack.append((0, y))
        if candidate(width - 1, y):
            stack.append((width - 1, y))
    mask = Image.new("L", source.size, 255)
    mask_pixels = mask.load()
    while stack:
        x, y = stack.pop()
        index = y * width + x
        if visited[index] or not candidate(x, y):
            continue
        visited[index] = 1
        mask_pixels[x, y] = 0
        if x:
            stack.append((x - 1, y))
        if x + 1 < width:
            stack.append((x + 1, y))
        if y:
            stack.append((x, y - 1))
        if y + 1 < height:
            stack.append((x, y + 1))
    mask = mask.filter(ImageFilter.GaussianBlur(1.1))
    result = source.convert("RGBA")
    result.putalpha(mask)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path, "PNG", optimize=True)
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
    """Partition transparent illustrated pixels into transformable body layers."""
    source = Image.open(reference_path).convert("RGBA")
    alpha = source.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        raise ValueError("Character reference has no visible pixels")
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    output_dir.mkdir(parents=True, exist_ok=True)

    def part_for(nx: float, ny: float) -> str:
        if ny < 0.235:
            return "head"
        if ny > 0.59:
            return "left_leg" if nx < 0.52 else "right_leg"
        if nx < 0.34:
            return "left_arm"
        if nx > 0.70:
            return "right_arm"
        return "torso"

    masks = {name: Image.new("L", source.size, 0) for name in (
        "head", "torso", "left_arm", "right_arm", "left_leg", "right_leg",
    )}
    mask_pixels = {name: mask.load() for name, mask in masks.items()}
    alpha_pixels = alpha.load()
    for y in range(top, bottom):
        ny = (y - top) / max(height, 1)
        for x in range(left, right):
            value = alpha_pixels[x, y]
            if not value:
                continue
            nx = (x - left) / max(width, 1)
            mask_pixels[part_for(nx, ny)][x, y] = value

    pivot_norm = {
        "head": (0.50, 0.92), "torso": (0.50, 0.30),
        "left_arm": (0.86, 0.12), "right_arm": (0.14, 0.12),
        "left_leg": (0.70, 0.08), "right_leg": (0.30, 0.08),
    }
    manifest: dict[str, Any] = {
        "rig_version": 1,
        "canvas_size": list(source.size),
        "source_bbox": list(bbox),
        "parts": {},
    }
    for name, mask in masks.items():
        # Slight overlap hides cut seams during restrained joint rotation while
        # retaining the source illustration's outer alpha silhouette.
        mask = ImageChops.darker(mask.filter(ImageFilter.MaxFilter(15)), alpha)
        part_bbox = mask.getbbox()
        if not part_bbox:
            continue
        layer = source.copy()
        layer.putalpha(mask)
        cropped = layer.crop(part_bbox)
        path = output_dir / f"{name}.png"
        cropped.save(path, "PNG", optimize=True)
        manifest["parts"][name] = {
            "path": str(path.resolve()),
            "position": [part_bbox[0], part_bbox[1]],
            "size": [part_bbox[2] - part_bbox[0], part_bbox[3] - part_bbox[1]],
            "pivot": list(pivot_norm[name]),
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
