"""Shot-aware cinematic AudioDirector. Planning is deterministic and auditable."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.audio.models import AudioEvent
from app.audio.voice_provider import create_local_voice_provider
from app.audio.voicepacks import VoicePackRegistry


_LEVELS = {"voice": -6.0, "dialogue": -8.0, "foley": -16.0, "sfx": -14.0, "ambience": -25.0, "music": -24.0}


class AudioDirector:
    """Turn story/shot facts into a frame-addressable audio plan, not audio files."""

    def __init__(self, voicepacks: VoicePackRegistry | None = None, sound_library: Path | None = None):
        self.voicepacks = voicepacks or VoicePackRegistry()
        self.sound_library = sound_library or Path(__file__).resolve().parents[2] / "sound_library"

    def plan(
        self,
        scenes: list[dict[str, Any]],
        output_dir: Path,
        language: str = "English",
        characters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not scenes:
            raise ValueError("AudioDirector requires at least one planned scene")
        narrator = self.voicepacks.narrator(language)
        provider = create_local_voice_provider(narrator)
        pronunciation = self._load_or_create(output_dir / "audio" / "pronunciation_dictionary.json")
        character_map = self._character_voice_map(characters or {}, narrator.voice_id)
        events: list[AudioEvent] = []
        shot_plans: list[dict[str, Any]] = []
        scene_cursor = 0.0

        for scene_index, scene in enumerate(scenes, 1):
            scene_id = scene.get("scene_id", scene_index)
            duration = float(scene.get("duration_seconds", 0) or 0)
            shots = scene.get("shots") or [{
                "id": f"{scene_id}A", "start": 0.0, "duration": duration or 5.0,
                "action": scene.get("character_action", "observe"),
                "emotion": scene.get("emotion", "neutral"),
                "subject": scene.get("visual_description", ""),
            }]
            duration = duration or sum(float(shot.get("duration", 0)) for shot in shots)
            location = self._location(scene)
            era = self._era(scene)
            scene_events: list[AudioEvent] = []

            # Location beds are continuous across the scene, with crossfades for clean looping.
            if "bank" in location:
                scene_events.extend([
                    self._event("ambience", scene_id, "bed", scene_cursor, duration, "bank_room_tone_1980s", -27, 0, "background", era=era),
                    self._event("ambience", scene_id, "fan", scene_cursor, duration, "ceiling_fan_period", -29, -.15, "background", era=era),
                    self._event("ambience", scene_id, "people", scene_cursor, duration, "distant_bank_people_1980s", -31, .2, "background", era=era),
                ])

            for shot_index, shot in enumerate(shots):
                shot_id = str(shot.get("id") or shot.get("shot_id") or f"{scene_id}_{shot_index + 1:02d}")
                start = scene_cursor + float(shot.get("start", sum(float(x.get("duration", 0)) for x in shots[:shot_index])))
                shot_duration = float(shot.get("duration", 5.0))
                action = str(shot.get("action", "observe")).lower().replace("_", " ")
                emotion = str(shot.get("emotion") or shot.get("expression") or scene.get("voice_emotion") or scene.get("emotion") or "serious").lower()
                visual = str(shot.get("subject") or scene.get("visual_description") or action)
                narration = str(shot.get("narration") or (scene.get("narration") if shot_index == 0 else "")).strip()
                shot_events: list[AudioEvent] = []
                if narration:
                    markup = self._speech_markup(narration, emotion)
                    estimated = min(max(1.0, len(narration.split()) / (150 * narrator.speaking_rate) * 60), shot_duration)
                    shot_events.append(AudioEvent(
                        audio_id=f"voice_{scene_id}_{shot_id}", type="voice", start_time=start,
                        duration=estimated, source=f"voicepack://{narrator.voice_id}", volume_db=_LEVELS["voice"],
                        fade_in=.02, fade_out=.08, priority=100, scene=scene_id, shot=shot_id,
                        character="narrator", emotion=emotion, layer="narration", text=markup,
                        language=narrator.language, pronunciation=pronunciation, asset_available=provider.available,
                    ))
                silence_duration = float(shot.get("silence_duration", 0) or 0)
                if silence_duration > 0:
                    shot_events.append(AudioEvent(
                        audio_id=f"silence_{scene_id}_{shot_id}", type="silence",
                        start_time=start + float(shot.get("silence_offset", 0)),
                        duration=min(silence_duration, shot_duration), source="intentional://silence",
                        volume_db=-60, priority=110, scene=scene_id, shot=shot_id,
                        emotion=emotion, layer="master", asset_available=True,
                        sync_action=str(shot.get("silence_reason", "authored dramatic pause")),
                    ))
                shot_events.extend(self._action_events(scene_id, shot_id, start, shot_duration, action, emotion, era))
                scene_events.extend(shot_events)
                shot_plans.append({
                    "scene": scene_id, "shot": shot_id, "start": round(start, 3), "duration": shot_duration,
                    "visual": visual, "action": action, "location": location, "era": era,
                    "emotion": emotion, "audio_event_ids": [event.audio_id for event in shot_events],
                })

            # Music is an authored segment, never an always-on blanket track.
            music_start = scene_cursor + min(4.0, duration * .2)
            music_duration = max(0.0, min(duration * .58, duration - (music_start - scene_cursor) - 1.0))
            if music_duration >= 2.0 and str(scene.get("music_mood", "subtle tension")).lower() not in {"none", "silence"}:
                scene_events.append(self._event("music", scene_id, "score", music_start, music_duration, "licensed_music_required", -24, 0, "music", emotion="restrained", era=era))
            events.extend(scene_events)
            scene_cursor += duration

        events.sort(key=lambda event: (event.start_time, -event.priority, event.audio_id))
        unresolved = sorted({event.source for event in events if not event.asset_available})
        plan = {
            "schema_version": "1.0", "audio_version": self._next_version(output_dir),
            "language": language, "duration": round(scene_cursor, 3),
            "narrator_voice_id": narrator.voice_id, "narrator_provider": narrator.provider,
            "voice_provider_available": provider.available,
            "voice_provider_status": provider.unavailable_reason or "ready",
            "mix_policy": {
                "voice_level_db": -6, "music_level_db": -24, "foley_level_db": -16,
                "sfx_level_db": -14, "ambience_level_db": -25,
                "voice_sidechain_duck_db": -8, "dialogue_sidechain_duck_db": -10,
                "target_lufs_i": -14, "true_peak_dbtp": -1.0,
            },
            "tracks": ["narration", "dialogue", "foley", "sfx", "ambience", "music"],
            "shots": shot_plans, "events": [event.to_dict() for event in events],
            "character_voice_map": character_map,
            "unresolved_assets": unresolved,
            "production_ready": provider.available and not unresolved,
        }
        self._write_package(output_dir, plan, pronunciation, character_map)
        return plan

    def _action_events(self, scene, shot, start, duration, action, emotion, era) -> list[AudioEvent]:
        events: list[AudioEvent] = []
        if any(word in action for word in ("walk", "approach", "enter")):
            events.append(self._event("foley", scene, f"{shot}_footsteps", start + .35, max(.6, duration - .7), "footsteps_indoor_leather", -16, -.08, "foley", shot, emotion, "foot contacts", era))
            events.append(self._event("foley", scene, f"{shot}_clothing", start + .2, max(.5, duration - .5), "cotton_clothing_movement", -24, .04, "foley", shot, emotion, "body movement", era))
        if "enter" in action or "door" in action:
            events.append(self._event("sfx", scene, f"{shot}_door", start + .18, min(1.4, duration), "wooden_bank_door_open_close", -14, -.25, "sfx", shot, emotion, "door contact", era))
        if "sit" in action:
            events.append(self._event("foley", scene, f"{shot}_clothing", start + .2, min(1.5, duration), "cotton_clothing_movement", -20, 0, "foley", shot, emotion, "body lowers", era))
            events.append(self._event("sfx", scene, f"{shot}_chair", start + min(1.6, duration * .45), min(.9, duration / 2), "wooden_chair_creak_impact", -15, .12, "sfx", shot, emotion, "body contacts chair", era))
        return events

    def _event(self, kind, scene, suffix, start, duration, source, volume, pan, layer, shot=None, emotion="neutral", sync=None, era="unspecified") -> AudioEvent:
        return AudioEvent(
            audio_id=f"{kind}_{scene}_{suffix}", type=kind, start_time=start, duration=max(.1, duration),
            source=f"library://{source}", volume_db=volume, pan=pan, fade_in=.12 if kind in {"ambience", "music"} else .03,
            fade_out=.3 if kind in {"ambience", "music"} else .08, priority={"voice": 100, "sfx": 75, "foley": 65, "ambience": 30, "music": 25}.get(kind, 50),
            scene=scene, shot=shot, emotion=emotion, layer=layer, sync_action=sync,
            asset_available=self._asset_available(source, era),
        )

    def _asset_available(self, sound_id: str, era: str) -> bool:
        catalog = self.sound_library / "catalog.json"
        if not catalog.is_file():
            return False
        try:
            entries = json.loads(catalog.read_text(encoding="utf-8")).get("sounds", [])
            return any(item.get("sound_id") == sound_id and item.get("available") and (item.get("era") in {None, "any", era}) for item in entries)
        except Exception:
            return False

    @staticmethod
    def _speech_markup(text: str, emotion: str) -> str:
        pace = .94 if emotion in {"serious", "dramatic", "tense", "mysterious"} else 1.0
        return f"<emotion={emotion}><speed={pace}>{text}</speed></emotion>"

    @staticmethod
    def _location(scene: dict) -> str:
        text = f"{scene.get('location', '')} {scene.get('visual_description', '')}".lower()
        return "1980s Bengaluru bank" if "bank" in text else (scene.get("location") or "unspecified location")

    @staticmethod
    def _era(scene: dict) -> str:
        text = f"{scene.get('era', '')} {scene.get('visual_description', '')}"
        match = re.search(r"\b(18|19|20)\d{2}s?\b", text)
        return match.group(0).rstrip("s") + "s" if match else str(scene.get("era") or "unspecified")

    @staticmethod
    def _character_voice_map(characters: dict, narrator_id: str) -> dict:
        result = {"narrator": {"voicepack": narrator_id, "role": "narration", "locked": True}}
        for character_id, data in sorted(characters.items()):
            voice_id = data.get("character_voice_id") if isinstance(data, dict) else None
            result[str(character_id)] = {"voicepack": voice_id, "role": "dialogue", "locked": True, "status": "configured" if voice_id else "voicepack_required"}
        return result

    @staticmethod
    def _load_or_create(path: Path) -> dict:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        data = {"Muthappa Rai": {"phonetic": "Moo-thap-pa Rye", "language": "kn-IN", "user_overridable": True}}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    @staticmethod
    def _next_version(output_dir: Path) -> str:
        versions = output_dir / "audio" / "versions"
        existing = [int(path.name.removeprefix("audio_v")) for path in versions.glob("audio_v[0-9][0-9][0-9]") if path.name.removeprefix("audio_v").isdigit()] if versions.exists() else []
        return f"audio_v{max(existing, default=0) + 1:03d}"

    @staticmethod
    def _write_package(output_dir: Path, plan: dict, pronunciation: dict, character_map: dict) -> None:
        audio = output_dir / "audio"
        for name in ("voice", "dialogue", "foley", "sfx", "ambience", "music", "mix", "reports", "versions"):
            (audio / name).mkdir(parents=True, exist_ok=True)
        version_dir = audio / "versions" / plan["audio_version"]
        version_dir.mkdir(parents=True, exist_ok=False)
        emotion_curve = {
            "segments": [
                {"start_percent": 0, "end_percent": 20, "emotion": "calm"},
                {"start_percent": 20, "end_percent": 40, "emotion": "curious"},
                {"start_percent": 40, "end_percent": 60, "emotion": "tension"},
                {"start_percent": 60, "end_percent": 75, "emotion": "high_tension"},
                {"start_percent": 75, "end_percent": 90, "emotion": "resolution"},
                {"start_percent": 90, "end_percent": 100, "emotion": "reflection"},
            ]
        }
        dependency = {
            "production_ready": plan["production_ready"],
            "voice_provider_available": plan["voice_provider_available"],
            "voice_provider_status": plan["voice_provider_status"],
            "unresolved_assets": plan["unresolved_assets"],
            "policy": "No unlicensed, random, or synthetic placeholder audio is substituted.",
        }
        documents = {
            "audio_plan.json": plan, "emotion_curve.json": emotion_curve,
            "character_voice_map.json": character_map,
            "pronunciation_dictionary.json": pronunciation,
            "reports/dependency_report.json": dependency,
        }
        for relative, data in documents.items():
            target = audio / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            version_target = version_dir / relative
            version_target.parent.mkdir(parents=True, exist_ok=True)
            version_target.write_text(json.dumps(data, indent=2), encoding="utf-8")
