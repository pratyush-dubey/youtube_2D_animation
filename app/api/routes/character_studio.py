"""User-friendly browser interface for local character generation."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator
import structlog

from app.characters.web_jobs import character_studio_jobs


router = APIRouter(tags=["character-studio"])
logger = structlog.get_logger(__name__)
_PAGE = Path(__file__).resolve().parents[1] / "web" / "character_studio.html"


class GenerateCharacterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=20, max_length=1800)
    mode: Literal["master", "full"] = "master"

    @field_validator("name", "description")
    @classmethod
    def no_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


@router.get("/character-studio", response_class=HTMLResponse)
def character_studio_page():
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"))


@router.get("/api/character-studio/status")
def character_studio_status():
    return character_studio_jobs.service_status()


@router.post("/api/character-studio/generate", status_code=202)
def generate_character(request: GenerateCharacterRequest):
    logger.info(
        "CHARACTER_GENERATION_REQUEST",
        stage="character_api",
        method="POST",
        endpoint="/api/character-studio/generate",
        mode=request.mode,
        name_length=len(request.name),
        description_length=len(request.description),
    )
    try:
        response = character_studio_jobs.create(request.name, request.description, request.mode)
        logger.info(
            "CHARACTER_GENERATION_RESPONSE",
            stage="character_api",
            job_id=response["id"],
            status=response["status"],
            http_status=202,
        )
        return response
    except RuntimeError as exc:
        logger.warning("CHARACTER_GENERATION_ERROR", stage="character_api", error=str(exc), http_status=409)
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/character-studio/jobs/latest")
def latest_character_job():
    return character_studio_jobs.latest() or {"status": "none"}


@router.get("/api/character-studio/jobs/{job_id}")
def character_job(job_id: str):
    job = character_studio_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/api/character-studio/jobs/{job_id}/images/{relative_path:path}")
def character_image(job_id: str, relative_path: str):
    path = character_studio_jobs.output_file(job_id, relative_path)
    if not path:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/png")


@router.post("/api/character-studio/jobs/{job_id}/open-folder")
def open_character_folder(job_id: str):
    try:
        return {"path": character_studio_jobs.open_folder(job_id)}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Job output folder not found") from exc
