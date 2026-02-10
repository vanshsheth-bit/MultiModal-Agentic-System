"""Milvus client utilities extracted from the original main.py.

The functions in this module intentionally mirror the original
implementation to preserve behavior while making them reusable from the
FastAPI app and services.
"""

from typing import Optional

try:
    from pymilvus import Collection, connections, utility  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    Collection = None  # type: ignore[assignment]
    connections = None  # type: ignore[assignment]
    utility = None  # type: ignore[assignment]

from .config import config


# Global variables for caching (same as original main.py)
_milvus_connection = None
_collection: Optional[Collection] = None


def get_milvus_connection():
    """Get or create Milvus connection (identical logic to original)."""

    if connections is None:
        raise RuntimeError("Milvus dependencies are not installed (missing 'pymilvus')")

    global _milvus_connection
    if _milvus_connection is None:
        try:
            _milvus_connection = connections.connect(
                host=config.MILVUS_HOST,
                port=config.MILVUS_PORT,
                timeout=60,
                keepalive=True,
            )
        except Exception as exc:  # pragma: no cover - defensive
            # Let callers decide how to surface the error
            raise exc
    return _milvus_connection


def get_collection() -> Collection:
    """Get or create collection (same as original get_collection)."""

    if Collection is None:
        raise RuntimeError("Milvus dependencies are not installed (missing 'pymilvus')")

    global _collection
    if _collection is None:
        get_milvus_connection()
        _collection = Collection(config.COLLECTION_NAME)
        _collection.load()
    return _collection


def collection_exists() -> bool:
    """Check whether the main collection exists in Milvus."""

    if utility is None:
        raise RuntimeError("Milvus dependencies are not installed (missing 'pymilvus')")

    get_milvus_connection()
    return bool(utility.has_collection(config.COLLECTION_NAME))


def get_user_partition(collection: Collection, user_id: int) -> str:
    """Return the name of the per-user partition, creating it if needed.

    This mirrors the partitioning strategy described in the design docs and
    can be used by ingestion/search code to keep vectors logically separated
    per user or organization.
    """

    partition_name = f"user_{user_id}"
    existing = [p.name for p in collection.partitions]
    if partition_name not in existing:
        collection.create_partition(partition_name)
    return partition_name
