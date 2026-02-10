"""Embedding utilities wrapping the existing OpenAI client usage."""

import hashlib
import json
import logging
from typing import Iterable, List

from sentence_transformers import SentenceTransformer  # type: ignore[import]
import torch

from .config import config
from ..db.redis import get_redis
from .cache import should_log_cache_metrics


_model: SentenceTransformer | None = None


logger = logging.getLogger(__name__)


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        requested = str(getattr(config, "EMBEDDING_DEVICE", "auto") or "auto").lower().strip()
        if requested in {"cuda", "gpu"}:
            device = "cuda"
        elif requested in {"cpu"}:
            device = "cpu"
        else:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        _model = SentenceTransformer(config.EMBEDDING_MODEL, trust_remote_code=True, device=device)
        logger.info("🧠 Embedding model loaded: model=%s device=%s", config.EMBEDDING_MODEL, device)
    return _model


def _cache_key_for_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # Version the cache key so changes to embedding generation (e.g. normalization)
    # do not reuse old cached vectors.
    version = "v2_norm"
    return f"emb:{version}:{digest}"


def get_embedding_cached(text: str) -> List[float]:
    """Return an embedding for ``text``, using Redis as a 7-day cache."""

    if not bool(getattr(config, "CACHE_ENABLED", True)) or not bool(
        getattr(config, "CACHE_EMBEDDINGS_ENABLED", True)
    ):
        model = _get_model()
        embedding = model.encode([text], normalize_embeddings=True)[0].tolist()
        return embedding  # type: ignore[no-any-return]

    redis = get_redis()
    key = _cache_key_for_text(text)

    cached = redis.get(key)
    if cached is not None:
        if should_log_cache_metrics():
            logger.info("CACHE emb hit key=%s", key[:40])
        return json.loads(cached)

    if should_log_cache_metrics():
        logger.info("CACHE emb miss key=%s", key[:40])

    model = _get_model()
    embedding = model.encode([text], normalize_embeddings=True)[0].tolist()

    ttl_s = int(getattr(config, "CACHE_EMBEDDINGS_TTL_S", 7 * 24 * 60 * 60))
    redis.setex(key, ttl_s, json.dumps(embedding))
    return embedding  # type: ignore[no-any-return]


def embed_text(text: str) -> List[float]:
    """Generate a single embedding for the given text.

    This uses ``get_embedding_cached`` to avoid repeated calls for identical
    text, preserving the external behavior while improving performance.
    """

    return get_embedding_cached(text)


def embed_batch(texts: Iterable[str]) -> List[List[float]]:
    """Generate embeddings for a batch of texts.

    Keeps behavior similar to the batching logic in the original
    DataIngestionFlow implementation.
    """

    texts_list = list(texts)
    if not texts_list:
        return []

    model = _get_model()
    embeddings = model.encode(texts_list, normalize_embeddings=True)
    return [e.tolist() for e in embeddings]  # type: ignore[no-any-return]
