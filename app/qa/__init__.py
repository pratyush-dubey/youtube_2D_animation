"""Objective post-render quality gates."""

from app.qa.media import inspect_render
from app.qa.identity import inspect_identity

__all__ = ["inspect_identity", "inspect_render"]
