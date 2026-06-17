from apps.api.routers.analytics import router as analytics_router
from apps.api.routers.auth import router as auth_router
from apps.api.routers.health import router as health_router
from apps.api.routers.sessions import router as sessions_router

__all__ = [
    "analytics_router",
    "auth_router",
    "health_router",
    "sessions_router",
]
