"""Replaceable, reference-aware image provider for production characters."""
from __future__ import annotations

import base64
import io
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

from app.characters.errors import CharacterGenerationError, DIFFUSION_FAILURE, LOCAL_DIFFUSION_FAILURE


BLOCKED_MESSAGE = (
    "Character image generation is not configured. Configure a genuine free/local "
    "reference-capable provider; primitive, SVG, and placeholder characters are forbidden."
)


class CharacterGenerationBlocked(CharacterGenerationError):
    pass


class CharacterImageProvider(ABC):
    name = "abstract"
    model = ""
    zero_cost = True
    supports_references = False

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def generate_master_character(self, prompt: str, output: Path) -> Path: ...
    @abstractmethod
    def generate_pose(self, prompt: str, reference: Path, output: Path) -> Path: ...
    @abstractmethod
    def generate_expression(self, prompt: str, reference: Path, output: Path) -> Path: ...
    @abstractmethod
    def generate_closeup(self, prompt: str, reference: Path, output: Path) -> Path: ...
    @abstractmethod
    def generate_turnaround(self, prompt: str, reference: Path, output: Path) -> Path: ...
    @abstractmethod
    def generate_body_parts(self, prompt: str, reference: Path, output: Path) -> Path: ...
    @abstractmethod
    def generate_variation(self, prompt: str, reference: Path, output: Path) -> Path: ...


class BlockedCharacterImageProvider(CharacterImageProvider):
    name = "unconfigured"

    def __init__(self, reason=BLOCKED_MESSAGE): self.reason = reason
    @property
    def configured(self): return False
    def _blocked(self, *args, **kwargs): raise CharacterGenerationBlocked(self.reason)
    generate_master_character = _blocked
    generate_pose = _blocked
    generate_expression = _blocked
    generate_closeup = _blocked
    generate_turnaround = _blocked
    generate_body_parts = _blocked
    generate_variation = _blocked


class Automatic1111CharacterProvider(CharacterImageProvider):
    """Local Stable Diffusion WebUI adapter; never installs or downloads models."""
    name = "automatic1111_local"
    model = "active_webui_checkpoint"
    supports_references = True

    def __init__(self, base_url: str): self.base_url = base_url.rstrip("/")

    @property
    def configured(self):
        try:
            import requests
            return requests.get(f"{self.base_url}/sdapi/v1/options", timeout=2).status_code == 200
        except Exception:
            return False

    def _request(self, prompt, output, reference=None, denoise=.32):
        if not self.configured: raise CharacterGenerationBlocked(BLOCKED_MESSAGE)
        import requests
        payload = {
            "prompt": prompt,
            "negative_prompt": "geometric human, vector mascot, primitive cartoon, malformed hands, extra fingers, extra limbs, inconsistent face, plastic skin, text, watermark",
            "width": 768, "height": 1024, "steps": 30, "cfg_scale": 6.5,
            "sampler_name": "DPM++ 2M Karras", "seed": 19850317,
        }
        endpoint = "txt2img"
        if reference:
            endpoint = "img2img"
            payload.update({"init_images": [base64.b64encode(reference.read_bytes()).decode()], "denoising_strength": denoise})
        response = requests.post(f"{self.base_url}/sdapi/v1/{endpoint}", json=payload, timeout=900)
        response.raise_for_status(); images = response.json().get("images") or []
        if not images: raise RuntimeError("Automatic1111 returned no character image")
        from PIL import Image
        image = Image.open(io.BytesIO(base64.b64decode(images[0].split(",")[-1]))).convert("RGB")
        output.parent.mkdir(parents=True, exist_ok=True); image.save(output, "PNG"); return output

    def generate_master_character(self, p, o): return self._request(p, o)
    def generate_pose(self, p, r, o): return self._request(p, o, r, .28)
    def generate_expression(self, p, r, o): return self._request(p, o, r, .22)
    def generate_closeup(self, p, r, o): return self._request(p, o, r, .24)
    def generate_turnaround(self, p, r, o): return self._request(p, o, r, .30)
    def generate_body_parts(self, p, r, o): return self._request(p, o, r, .20)
    def generate_variation(self, p, r, o): return self._request(p, o, r, .25)


class ComfyUICharacterProvider(CharacterImageProvider):
    """Primary local provider backed by the checked-in ComfyUI API workflow."""
    name = "comfyui_local"
    model = "DreamShaper_8_pruned.safetensors"
    supports_references = True

    def __init__(
        self,
        base_url: str,
        workflow: Path | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        from app.image_generation.comfyui_client import ComfyUIClient
        timeout = os.getenv("COMFYUI_GENERATION_TIMEOUT_SECONDS", os.getenv("COMFYUI_TIMEOUT_SECONDS", "1800"))
        self.client = ComfyUIClient(base_url, timeout=int(timeout))
        self.workflow = workflow or Path(__file__).resolve().parents[2] / "workflows" / "character_master.json"
        self.progress_callback = progress_callback

    @property
    def configured(self):
        if not self.workflow.is_file(): return False
        try:
            self.client.health(); return True
        except Exception:
            return False

    def _request(self, prompt, output, reference=None, denoise=1.0):
        if not self.configured:
            raise CharacterGenerationBlocked(BLOCKED_MESSAGE + " ComfyUI is selected but unreachable.")
        negative = (
            "3d render, vector mascot, primitive cartoon, child, teenager, old man, "
            "deformed anatomy, malformed hands, extra fingers, extra limbs, duplicate person, "
            "inconsistent face, asymmetrical eyes, plastic skin, white man, European man, Middle Eastern man, "
            "beard, stubble, handlebar moustache, curled moustache, long hair, mullet, bindi, tilak, suspenders, braces, "
            "mandarin collar, buttoned neck, coat, jacket, garment tied at waist, Victorian costume, fashion model, "
            "exaggerated long legs, uniform, lab coat, modern slim-fit clothing, photograph, 3d render, text, watermark"
        )
        try:
            return self.client.generate(
                self.workflow, prompt, output, reference=reference,
                negative_prompt=negative, width=512, height=768, steps=8 if reference else 12,
                cfg=6.5, seed=19850317, denoise=denoise, progress_callback=self.progress_callback,
            )
        except Exception as exc:
            detail = " ".join(str(exc).split())[:2000]
            raise CharacterGenerationError(f"{LOCAL_DIFFUSION_FAILURE} ComfyUI error: {detail}") from exc

    def generate_master_character(self, p, o): return self._request(p, o)
    def generate_pose(self, p, r, o): return self._request(p, o, r, .62)
    def generate_expression(self, p, r, o): return self._request(p, o, r, .48)
    def generate_closeup(self, p, r, o): return self._request(p, o, r, .52)
    def generate_turnaround(self, p, r, o): return self._request(p, o, r, .62)
    def generate_body_parts(self, p, r, o): return self._request(p, o, r, .25)
    def generate_variation(self, p, r, o): return self._request(p, o, r, .58)


class ImportedCharacterProvider(CharacterImageProvider):
    """Use only human-approved character images from a local import directory."""
    name = "imported_character_assets"
    model = "user_supplied"
    supports_references = True

    def __init__(self, import_dir: Path): self.import_dir = import_dir
    @property
    def configured(self): return self.import_dir.is_dir() and any(self.import_dir.rglob("*.png"))
    def _copy(self, output):
        matches = list(self.import_dir.rglob(output.name))
        if len(matches) != 1:
            raise CharacterGenerationBlocked(f"Expected exactly one imported {output.name}; found {len(matches)}")
        output.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(matches[0], output); return output
    def generate_master_character(self, p, o): return self._copy(o)
    def generate_pose(self, p, r, o): return self._copy(o)
    def generate_expression(self, p, r, o): return self._copy(o)
    def generate_closeup(self, p, r, o): return self._copy(o)
    def generate_turnaround(self, p, r, o): return self._copy(o)
    def generate_body_parts(self, p, r, o): return self._copy(o)
    def generate_variation(self, p, r, o): return self._copy(o)


class GeminiCharacterProvider(CharacterImageProvider):
    """Opt-in Gemini image adapter; never selected from a text-only model name."""
    name = "gemini_image"
    supports_references = True
    zero_cost = False

    def __init__(self):
        self.model = os.getenv("GEMINI_IMAGE_MODEL", "")
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.provider = None
    @property
    def configured(self): return bool(self.api_key and "image" in self.model.lower())
    def _request(self, prompt, output, reference=None):
        if not self.configured: raise CharacterGenerationBlocked("Gemini image provider is not explicitly configured with an image-capable model.")
        if self.provider is None:
            from app.images.gemini_provider import GeminiImagenProvider
            self.provider = GeminiImagenProvider(self.api_key)
        return self.provider.generate(prompt, output, reference_images=[reference] if reference else [])
    def generate_master_character(self, p, o): return self._request(p, o)
    def generate_pose(self, p, r, o): return self._request(p, o, r)
    def generate_expression(self, p, r, o): return self._request(p, o, r)
    def generate_closeup(self, p, r, o): return self._request(p, o, r)
    def generate_turnaround(self, p, r, o): return self._request(p, o, r)
    def generate_body_parts(self, p, r, o): return self._request(p, o, r)
    def generate_variation(self, p, r, o): return self._request(p, o, r)


def create_character_image_provider(
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> CharacterImageProvider:
    selected = os.getenv("CHARACTER_IMAGE_PROVIDER", "auto").strip().lower()
    if selected in {"auto", "comfyui", "local"}:
        provider = ComfyUICharacterProvider(
            os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188"),
            progress_callback=progress_callback,
        )
        if provider.configured: return provider
        if selected == "comfyui":
            return BlockedCharacterImageProvider(BLOCKED_MESSAGE + " ComfyUI is selected but unreachable.")
    if selected in {"auto", "imported"}:
        provider = ImportedCharacterProvider(Path(os.getenv("IMPORTED_CHARACTER_DIR", "assets/imported_characters")))
        if provider.configured: return provider
        if selected == "imported":
            return BlockedCharacterImageProvider(BLOCKED_MESSAGE + " Imported character assets are incomplete.")
    if selected in {"gemini", "gemini_image"}:
        provider = GeminiCharacterProvider()
        if provider.configured: return provider
        return BlockedCharacterImageProvider(BLOCKED_MESSAGE + " Gemini must use an explicitly configured image-capable model.")
    if selected in {"automatic1111", "a1111", "local"}:
        provider = Automatic1111CharacterProvider(os.getenv("A1111_BASE_URL", "http://127.0.0.1:7860"))
        if provider.configured: return provider
        return BlockedCharacterImageProvider(BLOCKED_MESSAGE + " Automatic1111 is selected but unreachable.")
    return BlockedCharacterImageProvider()
