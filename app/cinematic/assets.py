"""Structured production assets and auditable manifest records."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class AssetManifestEntry:
    asset_id: str
    type: str
    character: str | None
    scene: str
    shot: str
    resolution: tuple[int, int]
    source: str
    provider: str
    license: str
    generation_prompt: str
    created_at: str
    path: str
    content_sha256: str


class AssetManifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[AssetManifestEntry] = []
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.entries = [AssetManifestEntry(**item) for item in raw.get("assets", [])]

    def register(self, *, asset_id, asset_type, character, scene, shot, resolution,
                 source, provider, license_name, generation_prompt, path) -> AssetManifestEntry:
        asset_path = Path(path)
        if not asset_path.is_file():
            raise FileNotFoundError(asset_path)
        entry = AssetManifestEntry(
            asset_id=asset_id, type=asset_type, character=character, scene=scene, shot=shot,
            resolution=tuple(resolution), source=source, provider=provider, license=license_name,
            generation_prompt=generation_prompt,
            created_at=datetime.now(timezone.utc).isoformat(), path=str(asset_path.resolve()),
            content_sha256=hashlib.sha256(asset_path.read_bytes()).hexdigest(),
        )
        self.entries = [item for item in self.entries if item.asset_id != asset_id] + [entry]
        self.save()
        return entry

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "manifest_version": 1,
            "assets": [asdict(entry) for entry in sorted(self.entries, key=lambda item: item.asset_id)],
        }, indent=2), encoding="utf-8")
