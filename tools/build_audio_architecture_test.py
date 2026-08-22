"""Build the honest 30-second bank audio plan without fabricating missing assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.audio.director import AudioDirector


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("config/audio_bank_test_scene.json"))
    parser.add_argument("--output", type=Path, default=Path("output/audio_bank_test"))
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    plan = AudioDirector().plan(data["scenes"], args.output, data.get("language", "English"), data.get("characters", {}))
    print(json.dumps({
        "status": "planned" if plan["production_ready"] else "blocked_by_dependencies",
        "audio_plan": str(args.output / "audio" / "audio_plan.json"),
        "events": len(plan["events"]),
        "unresolved_assets": plan["unresolved_assets"],
        "voice_provider_status": plan["voice_provider_status"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
