from fastapi import APIRouter

from app.core.milvus_client import get_milvus_connection, collection_exists
from app.db.postgres import get_db_status
from app.db.redis import get_redis_status


router = APIRouter(tags=["health"])


def check_milvus() -> bool:
    try:
        get_milvus_connection()
        return collection_exists()
    except Exception:
        return False


@router.get("/health")
async def health_check() -> dict:
    return {
        "status": "healthy",
        "milvus": check_milvus(),
        "postgres": get_db_status(),
        "redis": get_redis_status(),
    }
