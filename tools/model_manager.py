"""Inspect the local D: image-model installation without downloading anything."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

AI_ROOT = Path(r"D:\AI_VIDEO_GENERATOR")
REGISTRY = {
    "DreamShaper_8_pruned.safetensors": {
        "relative_path": r"models\checkpoints\DreamShaper_8_pruned.safetensors",
        "sha256": "879db523c30d3b9017143d56705015e15a2cb5628762c11d086fed9538abd7fd",
        "license": "CreativeML OpenRAIL-M restrictions apply; see output/hardware/model_selection.json",
        "recommended_use": "512px cinematic illustrated characters; 768/1024 only if benchmark passes",
    }
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(verify: bool = False) -> dict:
    disk = shutil.disk_usage(AI_ROOT.anchor)
    models = []
    for name, metadata in REGISTRY.items():
        path = AI_ROOT / metadata["relative_path"]
        present = path.is_file()
        actual_hash = sha256(path) if present and verify else None
        models.append({
            "name": name, "location": str(path), "present": present,
            "size_bytes": path.stat().st_size if present else 0,
            "size_gb": round(path.stat().st_size / 1024**3, 3) if present else 0,
            "sha256_expected": metadata["sha256"], "sha256_actual": actual_hash,
            "checksum_ok": actual_hash == metadata["sha256"] if actual_hash else None,
            "license": metadata["license"], "recommended_use": metadata["recommended_use"],
        })
    return {
        "ai_root": str(AI_ROOT), "root_present": AI_ROOT.is_dir(),
        "disk": {"total_gb": round(disk.total / 1024**3, 2), "free_gb": round(disk.free / 1024**3, 2)},
        "models": models, "missing_files": [item["location"] for item in models if not item["present"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--verify", action="store_true")
    parser.add_argument("--json", action="store_true"); args = parser.parse_args()
    report = inspect(args.verify)
    if args.json: print(json.dumps(report, indent=2))
    else:
        print(f"AI root: {report['ai_root']} | free: {report['disk']['free_gb']} GB")
        for item in report["models"]:
            state = "installed" if item["present"] else "MISSING"
            checksum = f" | checksum={item['checksum_ok']}" if args.verify else ""
            print(f"{state}: {item['name']} | {item['size_gb']} GB | {item['location']}{checksum}")
            print(f"  license: {item['license']}")
            print(f"  use: {item['recommended_use']}")
    return 1 if report["missing_files"] else 0


if __name__ == "__main__": raise SystemExit(main())
