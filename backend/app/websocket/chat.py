from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ..core.query import QueryService
from ..db.postgres import SessionLocal
from ..models.database import QueryLog
from ..services.auth_service import decode_access_token


router = APIRouter()


@router.websocket("/ws/chat")
async def chat_websocket(ws: WebSocket) -> None:
    """WebSocket endpoint for streaming chat responses.

    Expects JSON messages of the form {"query": "..."} and streams back
    JSON chunks:

    - {"type": "token", "content": "..."}
    - {"type": "final", "answer": "...", "sources": [...], "latency_ms": 123}
    - {"type": "done"}
    """

    # Authenticate the websocket using a JWT access token passed as a query param.
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = decode_access_token(token)
    if payload is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()
    try:
        service = QueryService()
    except Exception:
        await ws.send_json(
            {
                "type": "error",
                "message": (
                    "Chat service is not ready. Ensure Milvus is running and the collection is created "
                    "(run ingestion to create/populate the collection)."
                ),
            }
        )
        await ws.close(code=1011)
        return

    try:
        while True:
            message = await ws.receive_json()
            query = message.get("query", "")
            if not query:
                await ws.send_json({"type": "error", "message": "Missing query"})
                continue

            result = service.process_query(query)
            answer = str(result.get("answer", ""))
            sources = result.get("sources", [])
            latency_ms = result.get("latency_ms")
            tool_confidence = result.get("tool_confidence")
            telemetry = result.get("telemetry") or {}

            # Derive a user_id from the token payload if present.
            raw_user_id = payload.get("id") or payload.get("sub")
            try:
                user_id = int(raw_user_id) if raw_user_id is not None else None
            except (TypeError, ValueError):
                user_id = None

            # Persist query log with telemetry so admin dashboard reflects WS usage.
            db = SessionLocal()
            try:
                log = QueryLog(
                    user_id=user_id,
                    query_text=query,
                    response=answer,
                    latency_ms=int(latency_ms) if latency_ms is not None else None,
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
                db.add(log)
                db.commit()
            finally:
                db.close()

            for token in answer.split():
                await ws.send_json({"type": "token", "content": token + " "})

            await ws.send_json(
                {
                    "type": "final",
                    "answer": answer,
                    "sources": sources,
                    "latency_ms": latency_ms,
                    "tool_confidence": tool_confidence,
                }
            )
            await ws.send_json({"type": "done"})
    except WebSocketDisconnect:
        return
