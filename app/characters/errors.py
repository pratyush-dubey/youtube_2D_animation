"""Character pipeline errors that must never trigger a primitive fallback."""


class CharacterGenerationError(RuntimeError):
    pass


DIFFUSION_FAILURE = "Diffusion character generation failed. Primitive fallback is disabled."
LOCAL_DIFFUSION_FAILURE = "Local diffusion generation failed. No substitute character was generated."
