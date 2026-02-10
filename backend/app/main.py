import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sentry_sdk
try:
    from prometheus_fastapi_instrumentator import Instrumentator
except ModuleNotFoundError:  # pragma: no cover
    Instrumentator = None  # type: ignore[assignment]

from app.api.v1.router import api_router
from app.middleware.logging import LoggingMiddleware
from app.middleware.error_handler import error_handler
from app.core.config import settings
try:
    from app.websocket.chat import router as ws_router
except ModuleNotFoundError:  # pragma: no cover
    ws_router = None  # type: ignore[assignment]

# Sentry initialization
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=1.0,
        environment=settings.ENVIRONMENT,
    )


_level_name = str(getattr(settings, "LOG_LEVEL", "INFO")).upper()
_level = getattr(logging, _level_name, logging.INFO)
logging.basicConfig(
    level=_level,
    format="%(asctime)s - %(process)d - %(name)s:%(lineno)d - %(levelname)s - %(message)s",
)


app = FastAPI(
    title="Multimodal RAG API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Middleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(LoggingMiddleware)
app.add_exception_handler(Exception, error_handler)

# Routers
app.include_router(api_router, prefix="/api/v1")
if ws_router is not None:
    app.include_router(ws_router)

# Prometheus metrics
if Instrumentator is not None:
    Instrumentator().instrument(app).expose(app)


@app.get("/")
def root() -> dict:
    return {"status": "healthy", "service": "multimodal-rag-api"}
