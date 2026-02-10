import json
import logging
from typing import Any, Dict, Optional

from ..db.redis import get_redis


logger = logging.getLogger(__name__)


_OCR_QUEUE_KEY = "ocr:queue"


def enqueue_ocr_job(*, doc_id: int, local_path: str) -> None:
    payload = {"doc_id": int(doc_id), "local_path": str(local_path)}
    client = get_redis()
    client.rpush(_OCR_QUEUE_KEY, json.dumps(payload))
    logger.info("🧾 Enqueued OCR job: doc_id=%s", doc_id)


def dequeue_ocr_job(*, timeout_s: int = 5) -> Optional[Dict[str, Any]]:
    client = get_redis()
    item = client.blpop(_OCR_QUEUE_KEY, timeout=int(timeout_s))
    if not item:
        return None
    _, raw = item
    try:
        return json.loads(raw)
    except Exception:
        return None
