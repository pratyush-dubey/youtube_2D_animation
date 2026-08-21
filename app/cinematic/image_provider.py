"""Replaceable shot-art generation with an explicit no-provider state."""
from __future__ import annotations

import hashlib
import base64
import io
import json
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


BLOCKED_MESSAGE = "Image generation provider is not configured."


class ImageGenerationBlocked(RuntimeError):
    pass


class ImageGenerationProvider(ABC):
    name: str
    model: str
    supports_references: bool = False
    zero_cost: bool = False

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def generate_character(self, prompt: str, output_path: Path, references=()) -> Path: ...
    @abstractmethod
    def generate_character_pose(self, prompt: str, output_path: Path, references=()) -> Path: ...
    @abstractmethod
    def generate_character_expression(self, prompt: str, output_path: Path, references=()) -> Path: ...
    @abstractmethod
    def generate_environment(self, prompt: str, output_path: Path, references=()) -> Path: ...
    @abstractmethod
    def generate_background(self, prompt: str, output_path: Path, references=()) -> Path: ...
    @abstractmethod
    def generate_prop(self, prompt: str, output_path: Path, references=()) -> Path: ...
    @abstractmethod
    def generate_shot(self, prompt: str, output_path: Path, references=()) -> Path: ...
    @abstractmethod
    def generate_reference_variation(self, prompt: str, output_path: Path, references=()) -> Path: ...


class UnconfiguredImageProvider(ImageGenerationProvider):
    name = "unconfigured"
    model = ""
    zero_cost = True

    def __init__(self, reason: str = BLOCKED_MESSAGE) -> None:
        self.reason = reason

    @property
    def configured(self) -> bool:
        return False

    def _blocked(self, *args, **kwargs):
        raise ImageGenerationBlocked(self.reason)

    generate_character = _blocked
    generate_character_pose = _blocked
    generate_character_expression = _blocked
    generate_environment = _blocked
    generate_background = _blocked
    generate_prop = _blocked
    generate_shot = _blocked
    generate_reference_variation = _blocked


class CachedImageProvider(ImageGenerationProvider):
    """Use user-approved existing artwork without synthesizing substitutes."""
    name = "cached"
    model = "user_assets"
    supports_references = True
    zero_cost = True

    def __init__(self, asset_map: dict[str, Path]) -> None:
        self.asset_map = asset_map

    @property
    def configured(self) -> bool:
        return bool(self.asset_map) and all(path.is_file() for path in self.asset_map.values())

    def _copy(self, operation, output_path):
        source = self.asset_map.get(operation)
        if not source or not source.is_file():
            raise ImageGenerationBlocked(f"Approved cached asset missing for {operation}.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return output_path

    def generate_character(self, prompt, output_path, references=()): return self._copy("character", output_path)
    def generate_character_pose(self, prompt, output_path, references=()): return self._copy("character_pose", output_path)
    def generate_character_expression(self, prompt, output_path, references=()): return self._copy("character_expression", output_path)
    def generate_environment(self, prompt, output_path, references=()): return self._copy("environment", output_path)
    def generate_background(self, prompt, output_path, references=()): return self._copy("background", output_path)
    def generate_prop(self, prompt, output_path, references=()): return self._copy("prop", output_path)
    def generate_shot(self, prompt, output_path, references=()): return self._copy("shot", output_path)
    def generate_reference_variation(self, prompt, output_path, references=()): return self._copy("reference_variation", output_path)


class GeminiImageProvider(ImageGenerationProvider):
    """Optional image-capable Gemini adapter; never used as the reasoning provider."""
    name = "gemini_image"
    supports_references = True
    zero_cost = False

    def __init__(self, model: str | None = None) -> None:
        from app.config.settings import settings
        self.model = model or settings.gemini_image_model
        self._provider = None
        self._api_key = settings.gemini_api_key

    @property
    def configured(self) -> bool:
        return bool(self._api_key and "image" in self.model.lower())

    def _generate(self, prompt, output_path, references):
        if not self.configured:
            raise ImageGenerationBlocked(BLOCKED_MESSAGE)
        if self._provider is None:
            from app.images.gemini_provider import GeminiImagenProvider
            self._provider = GeminiImagenProvider(self._api_key)
        return self._provider.generate(
            prompt, output_path, reference_images=[Path(item) for item in references]
        )

    def generate_character(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)
    def generate_character_pose(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)
    def generate_character_expression(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)
    def generate_environment(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)
    def generate_background(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)
    def generate_prop(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)
    def generate_shot(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)
    def generate_reference_variation(self, prompt, output_path, references=()): return self._generate(prompt, output_path, references)


class Automatic1111ImageProvider(ImageGenerationProvider):
    """Optional local Stable Diffusion WebUI adapter; no model download is performed here."""
    name = "automatic1111_local"
    model = "configured_webui_checkpoint"
    supports_references = True
    zero_cost = True

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        try:
            import requests
            return requests.get(f"{self.base_url}/sdapi/v1/options", timeout=2).status_code == 200
        except Exception:
            return False

    def _generate(self, prompt, output_path, references):
        import requests
        endpoint = "img2img" if references else "txt2img"
        payload = {
            "prompt": prompt, "negative_prompt": "watermark, text, extra limbs, distorted hands, duplicate people",
            "width": 1024, "height": 576, "steps": 28, "cfg_scale": 6.5,
            "sampler_name": "DPM++ 2M Karras",
        }
        if references:
            source = Path(references[0]).read_bytes()
            payload.update({"init_images": [base64.b64encode(source).decode()], "denoising_strength": 0.42})
        response = requests.post(f"{self.base_url}/sdapi/v1/{endpoint}", json=payload, timeout=600)
        response.raise_for_status()
        raw = response.json().get("images", [])
        if not raw:
            raise RuntimeError("Local Automatic1111 returned no image")
        from PIL import Image
        image = Image.open(io.BytesIO(base64.b64decode(raw[0].split(",")[-1]))).convert("RGB")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "PNG")
        return output_path

    def generate_character(self, p, o, references=()): return self._generate(p, o, references)
    def generate_character_pose(self, p, o, references=()): return self._generate(p, o, references)
    def generate_character_expression(self, p, o, references=()): return self._generate(p, o, references)
    def generate_environment(self, p, o, references=()): return self._generate(p, o, references)
    def generate_background(self, p, o, references=()): return self._generate(p, o, references)
    def generate_prop(self, p, o, references=()): return self._generate(p, o, references)
    def generate_shot(self, p, o, references=()): return self._generate(p, o, references)
    def generate_reference_variation(self, p, o, references=()): return self._generate(p, o, references)


class CachedGenerationProvider(ImageGenerationProvider):
    """Content-addressed wrapper that avoids regenerating identical artwork."""

    def __init__(self, inner: ImageGenerationProvider, cache_dir: Path) -> None:
        self.inner = inner
        self.cache_dir = cache_dir
        self.name = inner.name
        self.model = inner.model
        self.supports_references = inner.supports_references
        self.zero_cost = inner.zero_cost

    @property
    def configured(self):
        return self.inner.configured

    def _call(self, method, prompt, output_path, references):
        reference_hashes = [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in references]
        key = hashlib.sha256(json.dumps({
            "operation": method, "prompt": prompt, "references": reference_hashes,
            "model": self.model, "resolution": [1920, 1080],
        }, sort_keys=True).encode()).hexdigest()
        cached = self.cache_dir / f"{key}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if cached.is_file():
            shutil.copy2(cached, output_path)
            return output_path
        result = getattr(self.inner, method)(prompt, output_path, references)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result, cached)
        return output_path

    def generate_character(self, p, o, references=()): return self._call("generate_character", p, o, references)
    def generate_character_pose(self, p, o, references=()): return self._call("generate_character_pose", p, o, references)
    def generate_character_expression(self, p, o, references=()): return self._call("generate_character_expression", p, o, references)
    def generate_environment(self, p, o, references=()): return self._call("generate_environment", p, o, references)
    def generate_background(self, p, o, references=()): return self._call("generate_background", p, o, references)
    def generate_prop(self, p, o, references=()): return self._call("generate_prop", p, o, references)
    def generate_shot(self, p, o, references=()): return self._call("generate_shot", p, o, references)
    def generate_reference_variation(self, p, o, references=()): return self._call("generate_reference_variation", p, o, references)


def get_cinematic_image_provider(cache_dir: Path | None = None) -> ImageGenerationProvider:
    from app.config.settings import settings
    name = os.getenv("CINEMATIC_IMAGE_PROVIDER", settings.cinematic_image_provider).strip().lower()
    zero_cost_mode = os.getenv("ZERO_COST_MODE", str(settings.zero_cost_mode)).strip().lower() not in {"0", "false", "no"}
    if name in {"gemini", "gemini_image"}:
        inner = GeminiImageProvider()
        if zero_cost_mode:
            return UnconfiguredImageProvider(
                BLOCKED_MESSAGE + " Gemini image generation is available but paid and ZERO_COST_MODE is enabled."
            )
    elif name in {"automatic1111", "a1111", "local"}:
        inner = Automatic1111ImageProvider(settings.a1111_base_url)
        if not inner.configured:
            return UnconfiguredImageProvider(
                BLOCKED_MESSAGE + " Local Automatic1111 is selected but unreachable."
            )
    else:
        return UnconfiguredImageProvider()
    return CachedGenerationProvider(inner, cache_dir or Path("assets/cache/cinematic_images"))
