"""Local segmentation, manual masks, depth maps, and 2.5D layer records."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageFilter


class SegmentationFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class LayerAsset:
    layer_id: str
    category: str
    path: str
    mask_path: str
    depth: float
    parallax_speed: float
    z_index: int

    def __post_init__(self):
        if not 0 <= self.depth <= 1:
            raise ValueError("Layer depth must be between 0 and 1")
        if self.parallax_speed < 0:
            raise ValueError("Parallax speed cannot be negative")


class LocalLayerExtractor:
    """Extract layers with local rembg when present, or explicit assisted masks."""

    def extract_character(self, source: Path, output_dir: Path, manual_mask: Path | None = None) -> LayerAsset:
        output_dir.mkdir(parents=True, exist_ok=True)
        image = Image.open(source).convert("RGBA")
        if manual_mask and manual_mask.is_file():
            mask = Image.open(manual_mask).convert("L").resize(image.size, Image.Resampling.LANCZOS)
            method = "manual_assisted_mask"
        else:
            try:
                from rembg import remove
            except ImportError as exc:
                raise SegmentationFailed(
                    "Local segmentation is unavailable. Install rembg or supply an assisted mask."
                ) from exc
            result = remove(image)
            mask = result.getchannel("A")
            method = "local_rembg"
        visible = sum(mask.histogram()[16:])
        if visible < image.width * image.height * 0.03:
            raise SegmentationFailed("Character mask is empty or too small")
        cutout = image.copy()
        cutout.putalpha(mask.filter(ImageFilter.GaussianBlur(0.6)))
        path = output_dir / "character.png"
        mask_path = output_dir / "character_mask.png"
        cutout.save(path)
        mask.save(mask_path)
        (output_dir / "segmentation.json").write_text(json.dumps({
            "method": method, "source": str(source.resolve()), "mask": str(mask_path.resolve())
        }, indent=2), encoding="utf-8")
        return LayerAsset("character", "character", str(path), str(mask_path), 0.62, 1.0, 50)

    def extract_from_masks(self, source: Path, masks: dict[str, Path], layer_specs: dict[str, dict], output_dir: Path) -> list[LayerAsset]:
        image = Image.open(source).convert("RGBA")
        output_dir.mkdir(parents=True, exist_ok=True)
        layers = []
        for index, (layer_id, mask_path) in enumerate(masks.items()):
            if not mask_path.is_file():
                raise SegmentationFailed(f"Assisted mask is missing: {mask_path}")
            mask = Image.open(mask_path).convert("L").resize(image.size, Image.Resampling.LANCZOS)
            if mask.getbbox() is None:
                raise SegmentationFailed(f"Assisted mask is empty: {mask_path}")
            layer = image.copy()
            layer.putalpha(mask)
            path = output_dir / f"{layer_id}.png"
            layer.save(path)
            spec = layer_specs[layer_id]
            layers.append(LayerAsset(
                layer_id, spec["category"], str(path), str(mask_path.resolve()),
                float(spec["depth"]), float(spec["parallax_speed"]), int(spec.get("z_index", index)),
            ))
        return sorted(layers, key=lambda item: item.z_index)


def create_depth_map(layers: Iterable[LayerAsset], size: tuple[int, int], output_path: Path) -> Path:
    """Create a depth map from validated layer masks and explicit depth assignments."""
    depth = Image.new("L", size, 0)
    for layer in sorted(layers, key=lambda item: item.depth):
        mask = Image.open(layer.mask_path).convert("L").resize(size, Image.Resampling.LANCZOS)
        value = Image.new("L", size, round(layer.depth * 255))
        depth.paste(value, mask=mask)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    depth.filter(ImageFilter.GaussianBlur(1.0)).save(output_path)
    return output_path


def write_layer_manifest(layers: list[LayerAsset], depth_path: Path, output_path: Path) -> Path:
    output_path.write_text(json.dumps({
        "layers": [asdict(layer) for layer in layers],
        "depth_map": str(depth_path.resolve()),
        "depth_convention": "0.0 far background, 1.0 closest foreground",
    }, indent=2), encoding="utf-8")
    return output_path
