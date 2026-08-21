"""Route sub-package — all FastAPI APIRouter objects live here."""
from app.api.routes.projects import router as projects_router
from app.api.routes.jobs import router as jobs_router

__all__ = ["projects_router", "jobs_router"]
