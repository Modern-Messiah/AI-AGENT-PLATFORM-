from apps.api.routers.analytics import router as analytics_router
from apps.api.routers.auth import router as auth_router
from apps.api.routers.documents import router as documents_router
from apps.api.routers.health import router as health_router
from apps.api.routers.notebooks import router as notebooks_router
from apps.api.routers.sessions import router as sessions_router
from apps.api.routers.workflows import router as workflows_router

__all__ = [
    "analytics_router",
    "auth_router",
    "documents_router",
    "health_router",
    "notebooks_router",
    "sessions_router",
    "workflows_router",
]
