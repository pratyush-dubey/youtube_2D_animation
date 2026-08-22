"""Route sub-package — all FastAPI APIRouter objects live here."""
from app.api.routes.projects import router as projects_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.editor import router as editor_router
from app.api.routes.character_studio import router as character_studio_router
from app.api.routes.director import router as director_router

__all__ = ["projects_router", "jobs_router", "editor_router", "character_studio_router", "director_router"]
