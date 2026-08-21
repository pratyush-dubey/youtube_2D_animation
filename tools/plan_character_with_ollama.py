"""Have the local Ollama model review a character design before Blender generation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.llm.ollama_provider import OllamaProvider  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    design = json.loads(args.design.read_text(encoding="utf-8"))
    prompt = f"""
You are the local character art director for a zero-cost Blender/MPFB pipeline.
Review this fictional adult character design. Do not change identity, ethnicity, age, or
gender. Do not suggest paid tools, cloud APIs, or neural 3D generation. Return only JSON:
{{"approved": boolean, "silhouette_notes": [string], "material_notes": [string],
"motion_notes": [string], "quality_risks": [string]}}.
Design: {json.dumps(design)}
"""
    provider = OllamaProvider()
    if not provider.is_available():
        raise RuntimeError("Local Ollama server is unavailable")
    result, response = provider.generate_json(prompt, temperature=0.15, max_tokens=500)
    result.update({
        "provider": "ollama",
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cost_inr": 0,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
