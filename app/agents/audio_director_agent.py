"""Pipeline adapter for the shot-aware AudioDirector."""
from __future__ import annotations

from app.agents.base import Agent, AgentContext
from app.audio.director import AudioDirector


class AudioDirectorAgent(Agent):
    name = "audio_director"
    max_retries = 0

    def _execute(self, context: AgentContext) -> dict:
        if not context.storyboard:
            raise ValueError("StoryboardAgent must run before AudioDirectorAgent")
        plan = AudioDirector().plan(
            scenes=list(context.storyboard),
            output_dir=context.output_dir,
            language=context.language,
            characters=context.character_sheet,
        )
        context.audio_plan = plan
        context.character_voice_map = plan["character_voice_map"]
        if not plan["production_ready"]:
            context.warnings.append(
                "Audio plan created but dependencies are unresolved: "
                + ", ".join(plan["unresolved_assets"][:8])
            )
        return plan
