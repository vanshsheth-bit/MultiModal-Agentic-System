from fastapi import APIRouter

from .routes_health import router as health_router
from .routes_auth import router as auth_router
from .routes_admin import router as admin_router

try:
    from .routes_docs import router as docs_router
except ModuleNotFoundError:  # pragma: no cover
    docs_router = None  # type: ignore[assignment]

try:
    from .routes_query import router as query_router
except ModuleNotFoundError:  # pragma: no cover
    query_router = None  # type: ignore[assignment]


api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
if docs_router is not None:
    api_router.include_router(docs_router, prefix="/docs", tags=["documents"])
if query_router is not None:
    api_router.include_router(query_router, prefix="/query", tags=["query"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
