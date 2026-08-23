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
    """Raised with machine-readable ComfyUI failure context."""

    def __init__(self, message: str, *, http_status: int | None = None, details: Any = None, prompt_id: str | None = None):
        super().__init__(message)
        self.http_status = http_status
        self.details = details
        self.prompt_id = prompt_id


class ComfyUIClient:
    def __init__(
        self, base_url: str = "http://127.0.0.1:8188", timeout: int = 600,
        connect_timeout: int = 30, poll_interval: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.poll_interval = poll_interval
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
            with urlopen(request, timeout=self.connect_timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                details = json.loads(body)
            except ValueError:
                details = {"body": body[:3000]}
            raise ComfyUIError(
                f"ComfyUI HTTP {exc.code}: {body[:3000]}",
                http_status=exc.code, details=details,
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise ComfyUIError(f"ComfyUI is unreachable at {self.base_url}: {exc}") from exc

    def health(self) -> dict:
        return self._json("GET", "/system_stats")

    def checkpoints(self) -> list[str]:
        info = self._json("GET", "/object_info/CheckpointLoaderSimple")
        try:
            return list(info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0])
        except (KeyError, IndexError, TypeError) as exc:
            raise ComfyUIError("ComfyUI returned invalid CheckpointLoaderSimple object info", details=info) from exc

    def validate_checkpoint(self, checkpoint: str) -> None:
        available = self.checkpoints()
        if checkpoint not in available:
            raise ComfyUIError(
                f"Checkpoint not found in ComfyUI: {checkpoint}",
                details={"requested": checkpoint, "available": available},
            )

    @staticmethod
    def validate_workflow(workflow: dict) -> dict[str, str]:
        required = {
            "CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage",
            "KSampler", "VAEDecode", "SaveImage",
        }
        by_type: dict[str, list[str]] = {}
        for node_id, node in workflow.items():
            if not isinstance(node, dict) or not node.get("class_type") or not isinstance(node.get("inputs"), dict):
                raise ComfyUIError(f"Invalid workflow node {node_id}", details={"node_id": node_id, "node": node})
            by_type.setdefault(str(node["class_type"]), []).append(str(node_id))
        missing = sorted(required - set(by_type))
        if missing or len(by_type.get("CLIPTextEncode", [])) < 2:
            raise ComfyUIError(
                "Invalid workflow: required image-generation nodes are missing",
                details={"missing": missing, "node_types": by_type},
            )
        # Validate every node-to-node edge rather than assuming numeric IDs.
        for node_id, node in workflow.items():
            for name, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)):
                    if str(value[0]) not in {str(key) for key in workflow}:
                        raise ComfyUIError(
                            f"Invalid workflow connection at node {node_id}.{name}",
                            details={"node_id": node_id, "input": name, "connection": value},
                        )
        return {node_type: ids[0] for node_type, ids in by_type.items()}

    def queue_prompt(self, workflow: dict) -> str:
        logger.info("CHARACTER_GENERATION_REQUEST", stage="comfyui_submission", method="POST", url=f"{self.base_url}/prompt")
        result = self._json("POST", "/prompt", {"prompt": workflow, "client_id": self.client_id})
        if result.get("error") or result.get("node_errors"):
            details = {"error": result.get("error"), "node_errors": result.get("node_errors")}
            raise ComfyUIError(
                "ComfyUI rejected the workflow: "
                + json.dumps(details, default=str)[:3000], details=details,
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

    def wait(self, prompt_id: str, poll_seconds: float | None = None) -> dict:
        poll_seconds = self.poll_interval if poll_seconds is None else poll_seconds
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            history = self.history(prompt_id)
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                execution_error = self._execution_error(entry)
                if status.get("status_str") == "error" or execution_error:
                    details = execution_error or status
                    raise ComfyUIError(
                        f"ComfyUI workflow execution failed: {json.dumps(details, default=str)[:3000]}",
                        details=details, prompt_id=prompt_id,
                    )
                if entry.get("outputs"):
                    return entry
            time.sleep(poll_seconds)
        raise ComfyUIError(f"Workflow {prompt_id} exceeded {self.timeout}s", prompt_id=prompt_id)

    def download_image(self, image_info: dict, output: Path) -> Path:
        query = urlencode({k: image_info[k] for k in ("filename", "subfolder", "type") if k in image_info})
        try:
            with urlopen(self.base_url + "/view?" + query, timeout=self.connect_timeout) as response:
                image = response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ComfyUIError(f"Could not download ComfyUI image: {exc}") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(image)
        return output

    def _fit_reference(self, reference: Path, width: int, height: int) -> Path:
        """Resize a reference photo to the target latent's exact dimensions
        before it's VAE-encoded.

        The workflow has no resize node between LoadImage and VAEEncode, so
        without this the encoder runs on the reference's native resolution
        (a Wikimedia portrait can be up to 1400x1400) instead of the intended
        512x768-ish generation size - nearly 5x the pixel count, and on CPU
        that turned a ~6 minute text-to-image generation into one that still
        hadn't finished after 15 minutes. Matching dimensions up front is
        also what a real img2img call is supposed to receive.
        """
        from PIL import Image, ImageOps

        fitted = ImageOps.fit(Image.open(reference).convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
        fitted_path = reference.with_name(f"{reference.stem}_fit_{width}x{height}.png")
        fitted.save(fitted_path, "PNG")
        return fitted_path

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
            with urlopen(request, timeout=self.connect_timeout) as response:
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
        nodes = self.validate_workflow(workflow)
        checkpoint_node = workflow[nodes["CheckpointLoaderSimple"]]
        checkpoint = str(checkpoint_node["inputs"].get("ckpt_name", ""))
        self.validate_checkpoint(checkpoint)
        sampler_id = nodes["KSampler"]
        latent_id = nodes["EmptyLatentImage"]
        sampler = workflow[sampler_id]["inputs"]
        sampler.update({"seed": seed, "steps": steps, "cfg": cfg, "denoise": denoise})
        text_nodes = [node_id for node_id, node in workflow.items() if node["class_type"] == "CLIPTextEncode"]
        positive_id = str(sampler.get("positive", [text_nodes[0]])[0])
        negative_id = str(sampler.get("negative", [text_nodes[1]])[0])
        workflow[positive_id]["inputs"]["text"] = prompt
        workflow[negative_id]["inputs"]["text"] = negative_prompt
        workflow[latent_id]["inputs"].update({"width": width, "height": height, "batch_size": 1})
        if reference is not None:
            uploaded = self.upload_image(self._fit_reference(reference, width, height))
            load_id, encode_id = "visual_reference_load", "visual_reference_encode"
            workflow[load_id] = {"class_type": "LoadImage", "inputs": {"image": uploaded}}
            workflow[encode_id] = {"class_type": "VAEEncode", "inputs": {"pixels": [load_id, 0], "vae": [nodes["CheckpointLoaderSimple"], 2]}}
            workflow[sampler_id]["inputs"]["latent_image"] = [encode_id, 0]
        started = time.perf_counter()
        notify = progress_callback or (lambda _event, _details: None)
        notify("workflow_created", {"checkpoint": checkpoint, "node_count": len(workflow)})
        notify("submitting", {"endpoint": f"{self.base_url}/prompt"})
        prompt_id = self.queue_prompt(workflow)
        self.last_generation = {"prompt_id": prompt_id, "workflow": workflow, "started_at_monotonic": started}
        notify("generating", {"prompt_id": prompt_id})
        notify("waiting", {"prompt_id": prompt_id, "timeout_seconds": self.timeout, "poll_interval_seconds": self.poll_interval})
        try:
            entry = self.wait(prompt_id)
        except ComfyUIError as exc:
            if exc.prompt_id is None:
                exc.prompt_id = prompt_id
            raise
        notify("complete", {"prompt_id": prompt_id})
        notify("retrieving", {"prompt_id": prompt_id})
        for node in entry.get("outputs", {}).values():
            images = node.get("images") or []
            if images:
                notify("downloading", {"prompt_id": prompt_id, "image": images[0]})
                result = self.download_image(images[0], output)
                notify("retrieved", {"prompt_id": prompt_id, "output": str(result)})
                elapsed = round(time.perf_counter() - started, 3)
                self.last_generation.update({"generation_time": elapsed, "output": str(result)})
                notify("saved", {"prompt_id": prompt_id, "output": str(result), "generation_time": elapsed})
                logger.info("CHARACTER_GENERATION_RESPONSE", stage="comfyui", prompt_id=prompt_id, generation_time=elapsed, output=str(result))
                return result
        raise ComfyUIError(f"Workflow {prompt_id} completed without an image")
