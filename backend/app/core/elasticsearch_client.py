import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch

from .config import config


logger = logging.getLogger(__name__)


_es_client: Optional[Elasticsearch] = None


def get_es_client() -> Elasticsearch:
    global _es_client
    if _es_client is not None:
        return _es_client

    url = str(getattr(config, "ELASTICSEARCH_URL", "http://localhost:9200"))
    _es_client = Elasticsearch(url)
    return _es_client


def ensure_index(index_name: Optional[str] = None) -> str:
    index = str(index_name or getattr(config, "ELASTICSEARCH_INDEX", "multimodal_rag_chunks"))
    es = get_es_client()

    if es.indices.exists(index=index):
        return index

    mapping: Dict[str, Any] = {
        "mappings": {
            "properties": {
                "text": {"type": "text"},
                "source": {"type": "keyword"},
                "content_type": {"type": "keyword"},
                "page_number": {"type": "integer"},
                "timestamp_start": {"type": "float"},
                "timestamp_end": {"type": "float"},
                "language": {"type": "keyword"},
                "embedding_model": {"type": "keyword"},
                "ingestion_time": {"type": "long"},
                "confidence": {"type": "float"},
                "chunk_index": {"type": "integer"},
            }
        }
    }

    es.indices.create(index=index, **mapping)
    logger.info("✅ Elasticsearch index created: %s", index)
    return index


def delete_index(index_name: Optional[str] = None) -> None:
    index = str(index_name or getattr(config, "ELASTICSEARCH_INDEX", "multimodal_rag_chunks"))
    es = get_es_client()
    if es.indices.exists(index=index):
        es.indices.delete(index=index)
        logger.info("🗑️ Deleted Elasticsearch index: %s", index)


def bulk_index_chunks(chunks: List[Dict[str, Any]], index_name: Optional[str] = None) -> None:
    if not chunks:
        return

    index = ensure_index(index_name=index_name)
    es = get_es_client()

    actions: List[Dict[str, Any]] = []
    for c in chunks:
        source = str(c.get("source") or "")
        chunk_index = int(c.get("chunk_index") or 0)
        page_number = int(c.get("page_number") or 0)
        doc_id = f"{source}::{page_number}::{chunk_index}"
        actions.append({"index": {"_index": index, "_id": doc_id}})
        actions.append(
            {
                "text": c.get("text"),
                "source": c.get("source"),
                "content_type": c.get("content_type"),
                "page_number": c.get("page_number"),
                "timestamp_start": c.get("timestamp_start"),
                "timestamp_end": c.get("timestamp_end"),
                "language": c.get("language"),
                "embedding_model": c.get("embedding_model"),
                "ingestion_time": c.get("ingestion_time"),
                "confidence": c.get("confidence"),
                "chunk_index": c.get("chunk_index"),
            }
        )

    es.bulk(operations=actions, refresh=True)


def bm25_search(
    query: str,
    limit: int,
    source_filter: Optional[str] = None,
    content_type_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not query.strip():
        return []

    index = ensure_index()
    es = get_es_client()

    must: List[Dict[str, Any]] = [{"match": {"text": query}}]
    if source_filter:
        must.append({"term": {"source": source_filter}})
    if content_type_filter:
        must.append({"term": {"content_type": content_type_filter}})

    resp = es.search(
        index=index,
        size=int(limit),
        query={"bool": {"must": must}},
    )

    hits = (resp.get("hits") or {}).get("hits") or []
    results: List[Dict[str, Any]] = []
    for h in hits:
        src = h.get("_source") or {}
        results.append(
            {
                "text": src.get("text"),
                "source": src.get("source"),
                "content_type": src.get("content_type"),
                "page_number": src.get("page_number"),
                "timestamp_start": src.get("timestamp_start"),
                "timestamp_end": src.get("timestamp_end"),
                "language": src.get("language"),
                "embedding_model": src.get("embedding_model"),
                "ingestion_time": src.get("ingestion_time"),
                "confidence": src.get("confidence"),
                "chunk_index": src.get("chunk_index"),
                "bm25_score": h.get("_score"),
            }
        )

    return results
