"""Exercise the running Character Studio API and download its generated PNG."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8000"
OUTPUT = ROOT / "output" / "character_generation_test" / "api_test.png"
PAYLOAD = {
    "name": "API Connectivity Test",
    "description": (
        "cinematic 2D illustrated documentary character, adult Indian man, 28 years old, South Indian appearance, "
        "warm brown skin, natural human anatomy, realistic face, short black hair, neatly groomed short beard, "
        "olive green linen shirt, dark charcoal trousers, brown leather shoes, full body, standing, three-quarter view, "
        "professional digital illustration, painterly texture, cinematic lighting, detailed clothing, natural proportions, clean silhouette"
    ),
    "mode": "master",
}


def request_json(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(BASE_URL + path, data=body, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        raise RuntimeError(f"Character API HTTP {exc.code}: {exc.read().decode(errors='replace')[:2000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Character API connection failed: {exc}") from exc


def main() -> int:
    started = time.perf_counter()
    job = request_json("POST", "/api/character-studio/generate", PAYLOAD)
    deadline = time.monotonic() + 1800
    while job.get("status") in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(2)
        job = request_json("GET", f"/api/character-studio/jobs/{job['id']}")
    if job.get("status") != "complete":
        raise RuntimeError(json.dumps(job.get("failure") or job, default=str)[:3000])
    images = job.get("images") or []
    if not images:
        raise RuntimeError("Character API completed without exposing a PNG")
    path = "/".join(part.replace("%", "%25").replace(" ", "%20") for part in images[0].split("/"))
    image_url = f"{BASE_URL}/api/character-studio/jobs/{job['id']}/images/{path}"
    with urlopen(image_url, timeout=60) as response:
        image = response.read()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(image)
    print(json.dumps({"status": "PASS", "http_status": 202, "job_id": job["id"], "output": str(OUTPUT), "generation_time": round(time.perf_counter()-started, 3)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
