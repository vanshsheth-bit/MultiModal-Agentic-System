import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import check_rate_limit, get_current_user, get_db
from app.core.query import QueryService
from app.models.database import QueryLog
from app.models.requests import TextQueryRequest
from app.models.responses import QueryResponse


router = APIRouter(tags=["query"])


def _get_query_service() -> QueryService:
    try:
        return QueryService()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Query service is not ready. Ensure Milvus is running and the collection is created "
                "(run ingestion to create/populate the collection)."
            ),
        ) from exc


@router.post(
    "/text",
    response_model=QueryResponse,
    dependencies=[Depends(check_rate_limit)],
)
async def query_text(
    request: TextQueryRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryResponse:
    start_time = time.time()

    query_service = _get_query_service()
    result = query_service.process_query(
        request.query,
        source_filter=request.source_filter,
        content_type_filter=request.content_type_filter,
    )
    latency_ms = int((time.time() - start_time) * 1000)

    answer = str(result.get("answer", ""))
    sources = result.get("sources", [])
    tool_confidence = result.get("tool_confidence")
    telemetry = result.get("telemetry") or {}

    # Derive a user_id from the token payload if present.
    raw_user_id = current_user.get("id") or current_user.get("sub")  # type: ignore[union-attr]
    try:
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    query_log = QueryLog(
        user_id=user_id,
        query_text=request.query,
        response=answer,
        latency_ms=latency_ms,
        sources_count=len(sources),
        retrieval_confidence=telemetry.get("retrieval_confidence"),
        retrieval_supports=telemetry.get("retrieval_supports"),
        retrieval_hit=telemetry.get("retrieval_hit"),
        avg_vector_distance=telemetry.get("avg_vector_distance"),
        grounded=telemetry.get("grounded"),
        hallucination_flag=telemetry.get("hallucination_flag"),
        prompt_tokens=telemetry.get("prompt_tokens"),
        completion_tokens=telemetry.get("completion_tokens"),
        total_tokens=telemetry.get("total_tokens"),
        estimated_cost_usd=telemetry.get("estimated_cost_usd"),
    )
    db.add(query_log)
    db.commit()

    return QueryResponse(
        answer=answer,
        sources=sources,
        latency_ms=latency_ms,
        tool_confidence=tool_confidence,
    )


@router.post(
    "/audio",
    response_model=QueryResponse,
    dependencies=[Depends(check_rate_limit)],
)
async def query_audio(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryResponse:
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    start_time = time.time()
    query_service = _get_query_service()
    result = query_service.process_query("", audio_file=tmp_path)
    latency_ms = int((time.time() - start_time) * 1000)

    answer = str(result.get("answer", ""))
    sources = result.get("sources", [])

    raw_user_id = current_user.get("id") or current_user.get("sub")  # type: ignore[union-attr]
    try:
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    query_log = QueryLog(
        user_id=user_id,
        query_text="[audio]",
        response=answer,
        latency_ms=latency_ms,
        sources_count=len(sources),
        retrieval_confidence=telemetry.get("retrieval_confidence"),
        retrieval_supports=telemetry.get("retrieval_supports"),
        retrieval_hit=telemetry.get("retrieval_hit"),
        avg_vector_distance=telemetry.get("avg_vector_distance"),
        grounded=telemetry.get("grounded"),
        hallucination_flag=telemetry.get("hallucination_flag"),
        prompt_tokens=telemetry.get("prompt_tokens"),
        completion_tokens=telemetry.get("completion_tokens"),
        total_tokens=telemetry.get("total_tokens"),
        estimated_cost_usd=telemetry.get("estimated_cost_usd"),
    )
    db.add(query_log)
    db.commit()

    return QueryResponse(
        answer=answer,
        sources=sources,
        latency_ms=latency_ms,
        tool_confidence=tool_confidence,
    )


@router.get("/history")
async def get_query_history(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50,
):
    """Return recent query history for the current user.

    The shape of each log item matches what the frontend HistoryPage expects.
    """

    raw_user_id = current_user.get("id") or current_user.get("sub")  # type: ignore[union-attr]
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        # If we cannot determine a user id, return an empty history.
        return []

    logs = (
        db.query(QueryLog)
        .filter(QueryLog.user_id == user_id)
        .order_by(QueryLog.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": log.id,
            "query": log.query_text,
            "response": log.response,
            "latency_ms": log.latency_ms,
            "created_at": log.created_at.isoformat(),
            "sources_count": log.sources_count,
        }
        for log in logs
    ]
