"""API routers module."""

from .auth import router as auth_router
from .consultant import router as consultant_router
from .admin import router as admin_router

__all__ = ["auth_router", "consultant_router", "admin_router"]
