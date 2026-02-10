from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...api.deps import get_db
from ...core.config import config
from ...core.milvus_client import collection_exists, get_milvus_connection
from ...core.ingestion import IngestionService
from ...core.elasticsearch_client import delete_index
from ...models.database import Document, QueryLog, User

try:
    from pymilvus import utility  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    utility = None  # type: ignore[assignment]


router = APIRouter()


logger = logging.getLogger(__name__)


@router.get("/metrics")
async def get_metrics(db: Session = Depends(get_db)) -> dict:
    """Return analytics used by the admin/dashboard UI.

    This extends the basic metrics to include user counts, 7-day query
    history, and a dictionary of document counts per content type.
    """

    now = datetime.utcnow()
    last_24h = now - timedelta(days=1)
    last_7d = now - timedelta(days=7)

    total_documents = db.query(Document).count()
    total_queries = db.query(QueryLog).count()
    total_users = db.query(User).count()

    queries_last_24h = (
        db.query(QueryLog)
        .filter(QueryLog.created_at >= last_24h)
        .count()
    )

    queries_last_7d = (
        db.query(QueryLog)
        .filter(QueryLog.created_at >= last_7d)
        .count()
    )

    avg_latency = db.query(func.avg(QueryLog.latency_ms)).scalar() or 0

    # --- RAG telemetry aggregates ---
    def _safe_float(x):
        try:
            return float(x) if x is not None else 0.0
        except Exception:
            return 0.0

    q24 = db.query(QueryLog).filter(QueryLog.created_at >= last_24h)
    q7 = db.query(QueryLog).filter(QueryLog.created_at >= last_7d)

    total24 = q24.count()
    total7 = q7.count()

    hits24 = q24.filter(QueryLog.retrieval_hit.is_(True)).count()
    hits7 = q7.filter(QueryLog.retrieval_hit.is_(True)).count()

    grounded24 = q24.filter(QueryLog.grounded.is_(True)).count()
    grounded7 = q7.filter(QueryLog.grounded.is_(True)).count()

    halluc24 = q24.filter(QueryLog.hallucination_flag.is_(True)).count()
    halluc7 = q7.filter(QueryLog.hallucination_flag.is_(True)).count()

    avg_vec24 = q24.with_entities(func.avg(QueryLog.avg_vector_distance)).scalar()
    avg_vec7 = q7.with_entities(func.avg(QueryLog.avg_vector_distance)).scalar()

    avg_retr_conf24 = q24.with_entities(func.avg(QueryLog.retrieval_confidence)).scalar()
    avg_retr_conf7 = q7.with_entities(func.avg(QueryLog.retrieval_confidence)).scalar()

    sum_tokens24 = q24.with_entities(func.sum(QueryLog.total_tokens)).scalar() or 0
    sum_tokens7 = q7.with_entities(func.sum(QueryLog.total_tokens)).scalar() or 0

    sum_cost24 = q24.with_entities(func.sum(QueryLog.estimated_cost_usd)).scalar() or 0
    sum_cost7 = q7.with_entities(func.sum(QueryLog.estimated_cost_usd)).scalar() or 0

    retrieval_hit_rate_24h = (hits24 / float(total24)) if total24 else 0.0
    retrieval_hit_rate_7d = (hits7 / float(total7)) if total7 else 0.0
    grounded_rate_24h = (grounded24 / float(total24)) if total24 else 0.0
    grounded_rate_7d = (grounded7 / float(total7)) if total7 else 0.0

    docs_by_type_rows = (
        db.query(Document.content_type, func.count())
        .group_by(Document.content_type)
        .all()
    )
    documents_by_type = {
        (content_type or "unknown"): count for content_type, count in docs_by_type_rows
    }

    queries_by_day = [
        {
            "date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
            "count": db.query(QueryLog)
            .filter(
                QueryLog.created_at >= (now - timedelta(days=i)),
                QueryLog.created_at < (now - timedelta(days=i - 1)),
            )
            .count(),
        }
        for i in range(7, 0, -1)
    ]

    return {
        "total_documents": total_documents,
        "total_queries": total_queries,
        "total_users": total_users,
        "queries_last_24h": queries_last_24h,
        "queries_last_7d": queries_last_7d,
        "avg_latency_ms": float(avg_latency),
        "rag": {
            "retrieval_hit_rate_24h": retrieval_hit_rate_24h,
            "retrieval_hit_rate_7d": retrieval_hit_rate_7d,
            "grounded_rate_24h": grounded_rate_24h,
            "grounded_rate_7d": grounded_rate_7d,
            "hallucinations_24h": halluc24,
            "hallucinations_7d": halluc7,
            "avg_vector_distance_24h": _safe_float(avg_vec24) if avg_vec24 is not None else None,
            "avg_vector_distance_7d": _safe_float(avg_vec7) if avg_vec7 is not None else None,
            "avg_retrieval_confidence_24h": _safe_float(avg_retr_conf24) if avg_retr_conf24 is not None else None,
            "avg_retrieval_confidence_7d": _safe_float(avg_retr_conf7) if avg_retr_conf7 is not None else None,
            "total_tokens_24h": int(sum_tokens24 or 0),
            "total_tokens_7d": int(sum_tokens7 or 0),
            "estimated_cost_usd_24h": float(sum_cost24 or 0.0),
            "estimated_cost_usd_7d": float(sum_cost7 or 0.0),
        },
        "documents_by_type": documents_by_type,
        "queries_by_day": queries_by_day,
    }


@router.get("/system-status")
async def system_status() -> dict:
    return {"milvus_collection_exists": collection_exists()}


@router.post("/reindex")
async def reindex_knowledge_base() -> dict:
    """Drop and rebuild the Milvus collection by re-running ingestion.

    This is required when changing vector metric/index settings (e.g. switching
    from L2 to COSINE) and is also useful after uploading new documents.
    """

    if utility is None:
        raise HTTPException(status_code=500, detail="Milvus dependencies are not installed")

    try:
        get_milvus_connection()

        if bool(getattr(config, "HYBRID_SEARCH_ENABLED", True)):
            try:
                delete_index()
            except Exception as exc:  # pragma: no cover
                logger.warning("⚠️ Failed to delete Elasticsearch index before reindex: %s", exc)

        collection_name = str(getattr(config, "COLLECTION_NAME", "multimodal_rag"))
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)

        ingestion = IngestionService()
        ingestion.discover_files()
        ingestion.setup_vector_database()

        result = await ingestion.ingest_files_parallel()
        return result
    except Exception as exc:
        logger.exception("Reindex failed")
        raise HTTPException(
            status_code=500,
            detail=f"Reindex failed ({type(exc).__name__}): {repr(exc)}",
        ) from exc
