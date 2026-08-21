"""Configuration-driven selection with no primitive fallback."""
from pathlib import Path

from app.config.settings import settings
from app.providers.character3d.blocked_provider import BlockedCharacter3DProvider
from app.providers.character3d.local_provider import LocalCharacter3DProvider
from app.providers.character3d.mpfb_provider import MPFBCharacter3DProvider


def create_character3d_provider():
    selected = settings.character_3d_provider
    if selected == "mpfb":
        return MPFBCharacter3DProvider()
    if selected == "local":
        value = str(settings.local_character_model).strip()
        return LocalCharacter3DProvider(Path(value) if value else None)
    return BlockedCharacter3DProvider()
