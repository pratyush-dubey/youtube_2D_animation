"""Generate one bounded Gemini-keyframe + Veo motion proof and stop."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.settings import settings
from app.images.gemini_provider import GeminiImagenProvider
from app.qa.generative_motion import inspect_generative_motion
from app.qa.identity import inspect_identity
from app.video.veo_provider import VeoVideoProvider


OUT = ROOT / "output" / "proofs" / "muthappa_rai_veo"
REFERENCE = ROOT / "character_library" / "muthappa_rai" / "master" / "rig_neutral_v1.png"
KEYFRAME = OUT / "keyframe.jpg"
VIDEO = OUT / "walking_environment_test.mp4"

KEYFRAME_PROMPT = (
    "Historical documentary reconstruction, late 1980s Bengaluru street outside a modest bank, "
    "detailed cinematic hand-painted 2D animation keyframe, muted teal and warm ochre palette, "
    "natural daylight and long soft shadows. The adult Indian man from the supplied identity "
    "reference appears full-body in the left third, wearing the exact same black pinstripe suit, "
    "white open-collar shirt, sunglasses and black shoes. He stands at the beginning of a walk, "
    "both feet visible on the pavement, facing three-quarter right toward the bank entrance in the "
    "right third. Period-correct Ambassador taxi and two distant pedestrians in the background. "
    "Clear ground plane and contact shadows, coherent depth, no text, no watermark, no extra limbs."
)

MOTION_PROMPT = (
    "One continuous 8-second cinematic documentary shot at 24 fps. Preserve the exact illustrated "
    "person, face, sunglasses, moustache, hairstyle, body, suit, bank, street, palette and lighting "
    "from the supplied first frame. The man walks four deliberate steps toward the bank entrance: "
    "left and right legs visibly alternate, knees bend, opposite arms swing, hips shift weight, torso "
    "counter-rotates subtly, head remains stable, and each planted foot stays fixed on the pavement "
    "until toe-off. He decelerates naturally and stops near the door on balanced feet. A period taxi "
    "passes behind him and the two distant pedestrians continue walking independently; foliage and "
    "shadows move subtly. The camera performs a restrained lateral tracking move that supports but "
    "does not create the locomotion. Natural acceleration, contact, weight and follow-through. No "
    "cuts, no montage, no frozen pose, no sliding character card, no camera-only animation, no foot "
    "skating, no floating, no face morph, no extra limbs, no teleporting, no text or watermark."
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not REFERENCE.is_file():
        raise FileNotFoundError(REFERENCE)
    if not KEYFRAME.is_file():
        GeminiImagenProvider().generate(
            KEYFRAME_PROMPT, KEYFRAME, seed=1988, reference_images=[REFERENCE]
        )
    identity = inspect_identity(REFERENCE, KEYFRAME, OUT / "identity_report.json")
    if not VIDEO.is_file():
        VeoVideoProvider(model=settings.veo_model).generate_from_image(
            MOTION_PROMPT, KEYFRAME, VIDEO, duration_seconds=8,
            aspect_ratio="16:9", resolution=settings.veo_resolution,
            generate_audio=False, person_generation="allow_adult",
            negative_prompt=(
                "static image, frozen pose, slideshow, Ken Burns, camera-only motion, rigid PNG "
                "translation, foot sliding, floating feet, morphing face, extra limbs, broken anatomy, "
                "teleporting, jump cut, text, watermark"
            ), seed=1988,
        )
    motion = inspect_generative_motion(VIDEO, OUT / "motion_report.json")
    report = {
        "status": "PASS" if motion["passed"] else "FAIL",
        "bounded_visual_proof_only": True,
        "provider": "gemini_keyframe_plus_veo",
        "image_model": settings.gemini_image_model,
        "video_model": settings.veo_model,
        "duration_seconds": 8,
        "fps": motion["fps"],
        "identity": identity,
        "motion": {k: v for k, v in motion.items() if k != "samples"},
        "keyframe": str(KEYFRAME.resolve()),
        "video": str(VIDEO.resolve()),
    }
    (OUT / "quality_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if motion["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
