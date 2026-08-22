"""Build the canonical Arun character package without synthetic fallbacks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from app.characters.provider import CharacterImageProvider, create_character_image_provider
from app.characters.errors import CharacterGenerationError, DIFFUSION_FAILURE


POSES = ("standing", "walking", "sitting", "looking_left", "looking_right", "talking")
EXPRESSIONS = ("neutral", "happy", "sad", "angry", "concerned", "surprised")
MASTER_OUTPUTS = ("front", "3quarter", "side", "closeup", "fullbody")


def default_arun_bible() -> dict:
    return {
        "character_id": "arun_bank_employee_1985", "name": "Arun", "age": 35,
        "gender": "male", "height": "175 cm", "body_type": "medium build",
        "skin_tone": "medium warm-brown Indian complexion", "face_shape": "long oval",
        "jaw": "defined but not exaggerated", "nose": "straight medium-width nose with natural nostrils",
        "eyes": "deep brown almond-shaped eyes with visible eyelids", "eyebrows": "full, gently angled",
        "hair": "dense naturally wavy hair with individual strands and a natural hairline",
        "hair_color": "black", "hair_style": "short 1980s side part, modest volume",
        "facial_hair": "neatly trimmed medium moustache", "body_proportions": "7.5-head adult proportions; natural shoulders, elbows, hips, knees, hands and feet",
        "clothing": "cream cotton point-collar shirt with rolled cuffs, seams and folds; teal-grey tailored trousers; dark brown leather belt",
        "shoes": "dark brown lace-up leather shoes with believable sole and toe shape",
        "accessories": ["period wristwatch", "simple steel pen in shirt pocket"],
        "color_palette": ["aged cream", "muted teal-grey", "warm brown", "deep charcoal"],
        "art_style": "cinematic 2D digital illustration; stylized realism; painterly texture; controlled outlines",
        "era": "Bengaluru, 1985", "personality": "observant, diligent, reserved, quietly curious",
        "default_expression": "focused neutral", "reference_images": [], "master_reference": "master/front.png",
        "fictional": True, "disclosure": "Fictional dramatic-reconstruction character",
    }


def character_bible_from_prompt(name: str, description: str) -> dict:
    """Create a complete bible while letting the user's description drive the art."""
    bible = default_arun_bible()
    clean_name = " ".join(name.split())[:80] or "Character"
    bible.update({
        "character_id": clean_name.lower().replace(" ", "_") + "_custom",
        "name": clean_name,
        "custom_prompt": " ".join(description.split())[:1800],
        "identity_source": "user_description",
    })
    return bible


def plan_arun_with_ollama() -> dict:
    """Ask the installed local reasoning model for the structured design only."""
    from app.llm.ollama_provider import OllamaProvider
    defaults = default_arun_bible()
    provider = OllamaProvider(timeout=300)
    if not provider.is_available():
        raise RuntimeError("Ollama is not reachable")
    prompt = """You are a character art director. Design ONE fictional character for a high-end cinematic 2D animated documentary.
Character: Arun, 35, adult Indian male, Bengaluru bank employee in 1985, medium build.
Return ONLY a JSON object using exactly these keys: age, gender, height, body_type, skin_tone, face_shape, jaw, nose, eyes, eyebrows, hair, hair_color, hair_style, facial_hair, body_proportions, clothing, shoes, accessories, color_palette, art_style, era, personality, default_expression.
Require believable 7.5-head anatomy, natural hands/feet, period-correct clothing, detailed non-generic face, painterly texture, and consistent identity. No copyrighted studio imitation."""
    from app.llm.base import _extract_json
    response = provider.generate(prompt, temperature=.25, max_tokens=1400, max_retries=1)
    raw = _extract_json(response.content.strip())
    if raw is None:
        raise ValueError("Ollama returned an invalid character specification")
    for key in list(defaults):
        if key in raw and raw[key] not in (None, "", []): defaults[key] = raw[key]
    defaults["specification_source"] = {"provider": response.provider, "model": response.model, "cost_inr": 0}
    return defaults


class CharacterPackageBuilder:
    def __init__(
        self,
        output_dir: Path,
        provider: CharacterImageProvider | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ):
        self.output_dir = output_dir
        self.provider = provider or create_character_image_provider()
        self.progress_callback = progress_callback

    def _progress(self, message: str, completed: int, total: int) -> None:
        if self.progress_callback:
            self.progress_callback(message, completed, total)

    def run(self, bible: dict | None = None) -> dict:
        total = 12
        self._progress("Preparing character specification", 0, total)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "master").mkdir(exist_ok=True); (self.output_dir / "poses").mkdir(exist_ok=True)
        (self.output_dir / "expressions").mkdir(exist_ok=True); (self.output_dir / "rig").mkdir(exist_ok=True)
        (self.output_dir / "layers").mkdir(exist_ok=True)
        bible = bible or default_arun_bible()
        self._write("character_bible.json", bible)
        self._write("reference_analysis.json", {
            "character_id": bible["character_id"], "reference_type": "fictional_original_design",
            "external_reference_count": 0, "identity_source": "character_bible",
            "status": "ready_for_master_generation", "real_person": False,
        })
        prompts = self._prompts(bible)
        self._write("generation_manifest.json", {
            "provider": self.provider.name, "model": self.provider.model,
            "zero_cost": self.provider.zero_cost, "supports_references": self.provider.supports_references,
            "cache_key": hashlib.sha256(json.dumps({"bible": bible, "prompts": prompts}, sort_keys=True).encode()).hexdigest(),
            "prompts": prompts, "required_outputs": self.required_outputs(),
        })
        if not self.provider.configured:
            self._blocked_report(getattr(self.provider, "reason", "not configured"))
            raise CharacterGenerationError(DIFFUSION_FAILURE)
        if not self.provider.supports_references:
            self._blocked_report("Provider lacks reference-guided generation; identity consistency cannot be enforced.")
            raise CharacterGenerationError(DIFFUSION_FAILURE)

        front = self.output_dir / "master" / "front.png"
        if not front.is_file(): self.provider.generate_master_character(prompts["master_front"], front)
        self._progress("Created the master character", 1, total)
        completed = 1
        for name in ("3quarter", "side", "fullbody"):
            output = self.output_dir / "master" / f"{name}.png"
            if not output.is_file(): self.provider.generate_variation(prompts[f"master:{name}"], front, output)
            completed += 1; self._progress(f"Created {name} view", completed, total)
        closeup = self.output_dir / "master" / "closeup.png"
        if not closeup.is_file(): self.provider.generate_closeup(prompts["master:closeup"], front, closeup)
        completed += 1; self._progress("Created close-up view", completed, total)
        for name in POSES:
            output = self.output_dir / "poses" / f"{name}.png"
            if not output.is_file(): self.provider.generate_pose(prompts[f"pose:{name}"], front, output)
            completed += 1; self._progress(f"Created {name.replace('_', ' ')} pose", completed, total)
        self._beauty_sheet(self.output_dir / "character_beauty_sheet.png")
        self._progress("Created character beauty sheet", total, total)
        technical = self._technical_checks()
        # Segmentation is deliberately gated behind approved master/pose art.
        report = {
            "status": "manual_review_required", "manual_review_required": True, "production_approved": False,
            "technical_checks": technical,
            "identity_consistency": "manual_review_required", "face_quality": "manual_review_required",
            "anatomy_quality": "manual_review_required", "hand_quality": "manual_review_required",
            "clothing_quality": "manual_review_required", "hair_quality": "manual_review_required",
            "pose_quality": "manual_review_required", "style_consistency": "manual_review_required",
            "overall_score": "manual_review_required", "next_gate": "approve master and pose art before segmentation",
        }
        self._write("quality_report.json", report); self._write("character_quality_report.json", report); return report

    def generate_master_only(self, bible: dict | None = None) -> dict:
        self._progress("Preparing character specification", 0, 1)
        self.output_dir.mkdir(parents=True, exist_ok=True); (self.output_dir / "master").mkdir(exist_ok=True)
        for name in ("poses", "expressions", "layers", "rig"): (self.output_dir / name).mkdir(exist_ok=True)
        bible = bible or default_arun_bible(); prompts = self._prompts(bible)
        self._write("character_bible.json", bible)
        self._write("generation_manifest.json", {
            "provider": self.provider.name, "model": self.provider.model, "zero_cost": self.provider.zero_cost,
            "supports_references": self.provider.supports_references, "prompts": prompts,
            "required_outputs": self.required_outputs(),
        })
        if not self.provider.configured:
            self._blocked_report(getattr(self.provider, "reason", "not configured"))
            raise CharacterGenerationError(DIFFUSION_FAILURE)
        front = self.output_dir / "master" / "front.png"
        if not front.is_file(): self.provider.generate_master_character(prompts["master_front"], front)
        self._progress("Created the master character", 1, 1)
        report = {"status": "manual_review_required", "manual_review_required": True, "production_approved": False, "output": str(front), "next_gate": "inspect the front master before generating variations"}
        self._write("master_generation_report.json", report); return report

    def _blocked_report(self, reason):
        report = {
            "status": "blocked", "manual_review_required": True, "production_approved": False, "reason": reason,
            "identity_consistency": "not_evaluated", "face_quality": "not_evaluated",
            "anatomy_quality": "not_evaluated", "hand_quality": "not_evaluated",
            "clothing_quality": "not_evaluated", "hair_quality": "not_evaluated",
            "pose_quality": "not_evaluated", "style_consistency": "not_evaluated",
            "overall_score": "manual_review_required", "generated_images": 0,
            "next_action": "configure a genuine free/local reference-capable CharacterImageProvider",
        }
        self._write("quality_report.json", report); self._write("character_quality_report.json", report); return report

    def _prompts(self, bible):
        identity = "; ".join(f"{k}: {bible[k]}" for k in ("age", "skin_tone", "face_shape", "jaw", "nose", "eyes", "eyebrows", "hair_style", "facial_hair", "body_proportions", "clothing", "shoes"))
        style = "professional cinematic 2D digital illustration, stylized realism, detailed anatomy, natural hands, painterly skin and fabric texture, controlled outlines, neutral studio lighting, transparent or plain neutral background; no text"
        custom_prompt = bible.get("custom_prompt", "").strip()
        default_master = (
            "(full-body hand-painted 2D character illustration:1.3), front view, one 35-year-old "
            "South Indian man from Bengaluru, medium warm-brown skin, authentic South Indian facial features, "
            "long oval face, deep brown eyes, straight medium-width nose, small straight neatly trimmed black moustache, no beard, "
            "short wavy side-parted black hair, ordinary 1985 Bengaluru bank clerk, cream cotton open point-collar office shirt with steel pen, "
            "muted teal-grey straight tailored office trousers held by one dark brown belt, brown lace-up shoes, neutral stance, "
            "hands visible, reserved observant expression, cinematic illustrated documentary, painterly texture, "
            "natural 7.5-head adult anatomy, normal leg length, plain warm-grey studio background"
        )
        custom_master = (
            f"(full-body hand-painted 2D character illustration:1.3), front view, one character named {bible['name']}; "
            f"{custom_prompt}; preserve every identity, face, hair, clothing, age and era detail in this description; "
            "single person, neutral standing pose, entire body visible from head to shoes, hands visible, "
            "natural 7.5-head adult anatomy, believable face and hands, cinematic illustrated documentary, "
            "painterly texture, controlled outlines, plain warm-grey studio background, no text"
        )
        prompts = {"master_front": custom_master if custom_prompt else default_master}
        character_name = bible.get("name", "the character")
        for name, view in (("3quarter", "three-quarter front"), ("side", "strict side profile"), ("fullbody", "front full-body neutral stance")):
            prompts[f"master:{name}"] = f"Same exact {character_name} identity and wardrobe from the supplied master reference, {view}, full body. {style}"
        prompts["master:closeup"] = f"Dedicated head-and-shoulders close-up of the same exact {character_name}; preserve all facial geometry, hair and age details; detailed forehead, eyelids, eyes, nostrils, cheeks, lips, chin, jaw, ears, hairline, individual hair strands, clothing collar and cinematic key light. {style}"
        for pose in POSES: prompts[f"pose:{pose}"] = f"Same exact {character_name} from master reference in natural {pose.replace('_', ' ')} pose; preserve identity, proportions, clothing and era; believable hands and grounded shoes. {style}"
        for expression in EXPRESSIONS: prompts[f"expression:{expression}"] = f"Dedicated close-up of the same exact {character_name} with a subtle {expression} expression; preserve facial geometry, hairline and age. {style}"
        return prompts

    @staticmethod
    def required_outputs():
        roots = [f"master/{name}.png" for name in MASTER_OUTPUTS] + ["character_beauty_sheet.png"]
        return roots + [f"poses/{x}.png" for x in POSES]

    def _technical_checks(self):
        from PIL import Image
        checks = []
        for relative in self.required_outputs():
            path = self.output_dir / relative
            item = {"file": relative, "present": path.is_file(), "decodable": False}
            if path.is_file():
                try:
                    with Image.open(path) as image:
                        image.verify(); item.update({"decodable": True, "resolution": list(image.size)})
                except Exception as exc: item["error"] = str(exc)
            checks.append(item)
        return checks

    def _beauty_sheet(self, output):
        from PIL import Image, ImageDraw, ImageOps
        entries = [(name, self.output_dir / "master" / f"{name}.png") for name in MASTER_OUTPUTS]
        entries += [(name, self.output_dir / "poses" / f"{name}.png") for name in POSES]
        cell = (360, 480); sheet = Image.new("RGB", (cell[0] * 4, cell[1] * 3), "#222222")
        draw = ImageDraw.Draw(sheet)
        for index, (label, path) in enumerate(entries):
            with Image.open(path) as image:
                art = ImageOps.contain(image.convert("RGB"), (cell[0] - 20, cell[1] - 45))
            x = index % 4 * cell[0] + (cell[0] - art.width) // 2
            y = index // 4 * cell[1] + 8
            sheet.paste(art, (x, y)); draw.text((index % 4 * cell[0] + 12, index // 4 * cell[1] + cell[1] - 28), label, fill="white")
        output.parent.mkdir(parents=True, exist_ok=True); sheet.save(output, "PNG")

    def _write(self, name, data):
        path = self.output_dir / name; path.write_text(json.dumps(data, indent=2), encoding="utf-8"); return path
