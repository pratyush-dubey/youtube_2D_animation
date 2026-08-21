"""Centralized stylized-render profiles consumed by Blender."""
from __future__ import annotations

from copy import deepcopy

STYLE_PRESETS = {
    "CINEMATIC_TOON_3D": {
        "name": "cinematic_illustrated_3d",
        "render": {"toon": True, "outline": True, "shadow_steps": 3, "specular": 0.15, "roughness": 0.75},
        "lighting": {"soft_shadows": True, "rim_light": True, "ambient_occlusion": True},
        "post": {"film_grain": 0.04, "vignette": 0.10, "bloom": 0.05},
        "palette": {"shadow": [0.025, 0.04, 0.055], "mid": [0.12, 0.23, 0.24], "accent": [0.73, 0.39, 0.16]},
    },
    "CINEMATIC_2D": {"name": "cinematic_2d", "render": {"toon": True, "outline": False, "shadow_steps": 2}},
    "STORYBOOK_3D": {"name": "storybook_3d", "render": {"toon": True, "outline": True, "shadow_steps": 2}},
    "DARK_DOCUMENTARY": {"name": "dark_documentary", "render": {"toon": True, "outline": True, "shadow_steps": 3}},
    "ANIME_INSPIRED": {"name": "anime_inspired", "render": {"toon": True, "outline": True, "shadow_steps": 2}},
    "GRAPHIC_NOVEL": {"name": "graphic_novel", "render": {"toon": True, "outline": True, "shadow_steps": 2}},
    "MINIMAL_ILLUSTRATED": {"name": "minimal_illustrated", "render": {"toon": True, "outline": False, "shadow_steps": 2}},
}
DEFAULT_STYLE = "CINEMATIC_TOON_3D"


def resolve_style(name: str | None) -> dict:
    return deepcopy(STYLE_PRESETS.get(str(name or DEFAULT_STYLE).upper(), STYLE_PRESETS[DEFAULT_STYLE]))
