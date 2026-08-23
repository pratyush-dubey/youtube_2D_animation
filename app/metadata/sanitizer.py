"""Plain-text metadata boundary used by storage, rendering and UI responses."""
from __future__ import annotations

import html
import re
from typing import Any


_TAG = re.compile(r"<[^>]*>")


def sanitize_metadata_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG.sub("", text)
    return " ".join(text.split()).strip()


def sanitize_metadata_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    for key in ("best_title", "description", "category", "default_language"):
        if key in result:
            result[key] = sanitize_metadata_text(result[key])
    for key in ("tags", "hashtags"):
        if key in result:
            result[key] = [sanitize_metadata_text(item) for item in result[key] if sanitize_metadata_text(item)]
    if "chapters" in result:
        result["chapters"] = [
            {**chapter, "label": sanitize_metadata_text(chapter.get("label"))}
            for chapter in result["chapters"] if isinstance(chapter, dict)
        ]
    if "title_candidates" in result:
        result["title_candidates"] = [
            {
                **candidate,
                "title": sanitize_metadata_text(candidate.get("title")),
                "reason": sanitize_metadata_text(candidate.get("reason")),
            }
            for candidate in result["title_candidates"] if isinstance(candidate, dict)
        ]
    return result
