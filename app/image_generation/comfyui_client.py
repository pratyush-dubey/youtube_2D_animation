"""Small dependency-free client for ComfyUI's HTTP API."""
from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import structlog


logger = structlog.get_logger(__name__)


class ComfyUIError(RuntimeError):
    """Raised when ComfyUI is unavailable or rejects a workflow."""


class ComfyUIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: int = 1800):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = str(uuid.uuid4())
        self.last_generation: dict[str, Any] = {}

    def _json(self, method: str, path: str, payload: dict | None = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIError(f"ComfyUI HTTP {exc.code}: {body[:1000]}") from exc
        except (URLError, TimeoutError) as exc:
            raise ComfyUIError(f"ComfyUI is unreachable at {self.base_url}: {exc}") from exc

    def health(self) -> dict:
        return self._json("GET", "/system_stats")

    def queue_prompt(self, workflow: dict) -> str:
        logger.info("CHARACTER_GENERATION_REQUEST", stage="comfyui_submission", method="POST", url=f"{self.base_url}/prompt")
        result = self._json("POST", "/prompt", {"prompt": workflow, "client_id": self.client_id})
        if result.get("error") or result.get("node_errors"):
            raise ComfyUIError(
                "ComfyUI rejected the workflow: "
                + json.dumps({"error": result.get("error"), "node_errors": result.get("node_errors")}, default=str)[:3000]
            )
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"ComfyUI did not return a prompt id: {result}")
        return str(prompt_id)

    def history(self, prompt_id: str) -> dict:
        return self._json("GET", f"/history/{prompt_id}")

    @staticmethod
    def _execution_error(entry: dict) -> dict | None:
        for message in entry.get("status", {}).get("messages", []):
            if isinstance(message, list) and message and message[0] == "execution_error":
                return message[1] if len(message) > 1 and isinstance(message[1], dict) else {"message": str(message)}
        return None

    def wait(self, prompt_id: str, poll_seconds: float = 1.0) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            history = self.history(prompt_id)
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                execution_error = self._execution_error(entry)
                if status.get("status_str") == "error" or execution_error:
                    details = execution_error or status
                    raise ComfyUIError(f"ComfyUI workflow execution failed: {json.dumps(details, default=str)[:3000]}")
                if entry.get("outputs"):
                    return entry
            time.sleep(poll_seconds)
        raise ComfyUIError(f"Workflow {prompt_id} exceeded {self.timeout}s")

    def download_image(self, image_info: dict, output: Path) -> Path:
        query = urlencode({k: image_info[k] for k in ("filename", "subfolder", "type") if k in image_info})
        try:
            with urlopen(self.base_url + "/view?" + query, timeout=60) as response:
                image = response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ComfyUIError(f"Could not download ComfyUI image: {exc}") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(image)
        return output

    def upload_image(self, image: Path, overwrite: bool = True) -> str:
        boundary = "----CodexComfyBoundary" + uuid.uuid4().hex
        content = image.read_bytes()
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{image.name}\"\r\nContent-Type: image/png\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\n{str(overwrite).lower()}\r\n--{boundary}--\r\n".encode(),
        ]
        request = Request(
            self.base_url + "/upload/image",
            data=b"".join(parts),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ComfyUIError(f"Could not upload reference image: {exc}") from exc
        return str(result.get("name") or image.name)

    def generate(
        self,
        workflow_template: Path,
        prompt: str,
        output: Path,
        *,
        reference: Path | None = None,
        negative_prompt: str = "",
        width: int = 512,
        height: int = 768,
        steps: int = 20,
        cfg: float = 6.5,
        seed: int = 19850317,
        denoise: float = 1.0,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> Path:
        workflow = json.loads(workflow_template.read_text(encoding="utf-8"))
        workflow = deepcopy(workflow)
        workflow["3"]["inputs"].update({"seed": seed, "steps": steps, "cfg": cfg, "denoise": denoise})
        workflow["6"]["inputs"]["text"] = prompt
        workflow["7"]["inputs"]["text"] = negative_prompt
        workflow["5"]["inputs"].update({"width": width, "height": height})
        if reference is not None:
            uploaded = self.upload_image(reference)
            workflow["10"] = {"class_type": "LoadImage", "inputs": {"image": uploaded}}
            workflow["11"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}}
            workflow["3"]["inputs"]["latent_image"] = ["11", 0]
        started = time.perf_counter()
        notify = progress_callback or (lambda _event, _details: None)
        notify("submitting", {"endpoint": f"{self.base_url}/prompt"})
        prompt_id = self.queue_prompt(workflow)
        self.last_generation = {"prompt_id": prompt_id, "workflow": workflow, "started_at_monotonic": started}
        notify("generating", {"prompt_id": prompt_id})
        entry = self.wait(prompt_id)
        notify("retrieving", {"prompt_id": prompt_id})
        for node in entry.get("outputs", {}).values():
            images = node.get("images") or []
            if images:
                result = self.download_image(images[0], output)
                elapsed = round(time.perf_counter() - started, 3)
                self.last_generation.update({"generation_time": elapsed, "output": str(result)})
                notify("saved", {"prompt_id": prompt_id, "output": str(result), "generation_time": elapsed})
                logger.info("CHARACTER_GENERATION_RESPONSE", stage="comfyui", prompt_id=prompt_id, generation_time=elapsed, output=str(result))
                return result
        raise ComfyUIError(f"Workflow {prompt_id} completed without an image")
