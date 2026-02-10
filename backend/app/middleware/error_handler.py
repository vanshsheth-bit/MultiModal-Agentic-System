from fastapi import Request
from fastapi.responses import JSONResponse


async def error_handler(request: Request, exc: Exception) -> JSONResponse:  # type: ignore[override]
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
