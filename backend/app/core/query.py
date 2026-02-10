"""Query processing and RAG orchestration logic.

This version includes aggressive tuning to force CrewAI to complete successfully.
"""

import logging
import os
import re
import time
from dataclasses import dataclass
import math
import hashlib
from typing import Any, Dict, List, Optional

from crewai import Agent, Crew, Task  # type: ignore[import]
from langchain_core.pydantic_v1 import BaseModel, Field, PrivateAttr  # type: ignore[import]
from langchain_core.tools import BaseTool  # type: ignore[import]
from openai import OpenAI  # type: ignore[import]
from pymilvus import Collection  # type: ignore[import]

from .audio import transcribe_audio_file
from .config import config
from .embeddings import embed_text
from .elasticsearch_client import bm25_search
from .milvus_client import get_collection
from .cache import cache_get_json, cache_set_json, make_cache_key, should_log_cache_metrics
from .tool_confidence import (
    llm_confidence,
    retrieval_confidence_from_sources,
    transcription_confidence,
)


def _estimate_tokens(text: str) -> int:
    # Cheap and dependency-free: approx 4 chars per token.
    t = str(text or "")
    return max(0, int(len(t) / 4))

try:
    from sentence_transformers.cross_encoder import CrossEncoder  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    CrossEncoder = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


@dataclass
class QueryState:
    """State container mirroring the original QueryState."""

    query: str = ""
    transcribed_query: str = ""
    search_results: str = ""
    final_response: str = ""
    audio_file: Optional[str] = None


class QueryService:
    """Service that encapsulates query processing logic."""

    def __init__(self) -> None:
        self.collection: Collection = get_collection()
        self._reranker = None

    def _get_reranker(self):
        if not bool(getattr(config, "RERANK_ENABLED", True)):
            return None
        if CrossEncoder is None:
            return None
        if self._reranker is not None:
            return self._reranker
        try:
            model_name = str(getattr(config, "RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"))
            self._reranker = CrossEncoder(model_name)
            return self._reranker
        except Exception as exc:
            logger.warning("Reranker unavailable; continuing without reranking: %s", exc)
            self._reranker = None
            return None

    def _rerank_results(self, query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        reranker = self._get_reranker()
        if reranker is None or not results:
            return results

        try:
            cache_enabled = bool(getattr(config, "CACHE_ENABLED", True)) and bool(
                getattr(config, "CACHE_RERANK_ENABLED", True)
            )
            ttl_s = int(getattr(config, "CACHE_RERANK_TTL_S", 24 * 60 * 60))
            model_name = str(getattr(config, "RERANK_MODEL", ""))

            def item_fingerprint(r: Dict[str, Any]) -> str:
                base = f"{r.get('source')}::{int(r.get('page_number') or 0)}::{int(r.get('chunk_index') or 0)}"
                text = str(r.get("text") or "")
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                return f"{base}::{digest}"

            scored: List[Dict[str, Any]] = []
            pairs_to_score: List[tuple[str, str]] = []
            idx_to_key: List[str] = []
            cache_hits = 0
            cache_misses = 0

            for r in results:
                r2 = dict(r)
                if not cache_enabled:
                    idx_to_key.append("")
                    pairs_to_score.append((query, str(r.get("text") or "")))
                    continue

                fp = item_fingerprint(r)
                key = make_cache_key(
                    prefix="rerank",
                    version="v1",
                    payload={"model": model_name, "q": query, "item": fp},
                )
                cached = cache_get_json(key)
                if cached is not None:
                    try:
                        r2["rerank_score"] = float(cached)
                        scored.append(r2)
                        cache_hits += 1
                        continue
                    except Exception:
                        pass

                cache_misses += 1
                idx_to_key.append(key)
                pairs_to_score.append((query, str(r.get("text") or "")))
                scored.append(r2)

            # Score only missing ones, then write-through to cache
            if pairs_to_score:
                scores = reranker.predict(pairs_to_score)
                score_i = 0
                for r2 in scored:
                    if "rerank_score" in r2:
                        continue
                    s = float(scores[score_i])
                    r2["rerank_score"] = s
                    key = idx_to_key[score_i] if score_i < len(idx_to_key) else ""
                    if cache_enabled and key:
                        cache_set_json(key=key, value=s, ttl_s=ttl_s)
                    score_i += 1

            if cache_enabled and should_log_cache_metrics():
                logger.info(
                    "CACHE rerank hits=%d misses=%d model=%s",
                    cache_hits,
                    cache_misses,
                    model_name,
                )

            scored.sort(key=lambda x: float(x.get("rerank_score") or 0.0), reverse=True)
            return scored
        except Exception as exc:
            logger.warning("Reranking failed; continuing without reranking: %s", exc)
            return results

    def search_vector_database(
        self,
        query: str,
        limit: Optional[int] = None,
        source_filter: Optional[str] = None,
        content_type_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search vector database for relevant information (same as original)."""

        try:
            candidate_limit = int(limit or getattr(config, "RETRIEVAL_CANDIDATES", 20))
            use_hybrid = bool(getattr(config, "HYBRID_SEARCH_ENABLED", True))

            retrieval_cache_key = None
            if bool(getattr(config, "CACHE_ENABLED", True)) and bool(
                getattr(config, "CACHE_RETRIEVAL_ENABLED", True)
            ):
                retrieval_cache_key = make_cache_key(
                    prefix="retrieval",
                    version="v4",
                    payload={
                        "q": query,
                        "limit": candidate_limit,
                        "use_hybrid": use_hybrid,
                        "source_filter": source_filter,
                        "content_type_filter": content_type_filter,
                        "metric": str(getattr(config, "VECTOR_METRIC", "COSINE")),
                        "alpha": float(getattr(config, "HYBRID_ALPHA", 0.5)),
                        "bm25_limit": int(getattr(config, "BM25_CANDIDATES", 50)),
                        "embed_model": str(getattr(config, "EMBEDDING_MODEL", "")),
                    },
                )
                cached = cache_get_json(retrieval_cache_key)
                if isinstance(cached, list):
                    if should_log_cache_metrics():
                        logger.info("CACHE retrieval hit key=%s", str(retrieval_cache_key)[:50])
                    return cached  # type: ignore[return-value]
                if should_log_cache_metrics():
                    logger.info("CACHE retrieval miss key=%s", str(retrieval_cache_key)[:50])

            query_embedding = embed_text(query)

            search_params = {
                "metric_type": getattr(config, "VECTOR_METRIC", "COSINE"),
                "params": {"nprobe": 10},
            }

            expr_parts: List[str] = []
            if source_filter:
                safe = str(source_filter).replace('\\', "\\\\").replace('"', "\\\"")
                expr_parts.append(f'source == "{safe}"')
            if content_type_filter:
                safe_ct = str(content_type_filter).replace('\\', "\\\\").replace('"', "\\\"")
                expr_parts.append(f'content_type == "{safe_ct}"')
            expr: str | None = " && ".join(expr_parts) if expr_parts else None
            results = self.collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=candidate_limit,
                expr=expr,
                output_fields=[
                    "text",
                    "source",
                    "content_type",
                    "page_number",
                    "timestamp_start",
                    "timestamp_end",
                    "language",
                    "embedding_model",
                    "ingestion_time",
                    "confidence",
                    "chunk_index",
                ],
            )

            vector_results: List[Dict[str, Any]] = []
            for hits in results:
                for hit in hits:
                    vector_results.append(
                        {
                            "text": hit.entity.get("text"),
                            "source": hit.entity.get("source"),
                            "content_type": hit.entity.get("content_type"),
                            "page_number": hit.entity.get("page_number"),
                            "timestamp_start": hit.entity.get("timestamp_start"),
                            "timestamp_end": hit.entity.get("timestamp_end"),
                            "language": hit.entity.get("language"),
                            "embedding_model": hit.entity.get("embedding_model"),
                            "ingestion_time": hit.entity.get("ingestion_time"),
                            "confidence": hit.entity.get("confidence"),
                            "chunk_index": hit.entity.get("chunk_index"),
                            "score": hit.score,
                            "vector_score": hit.score,
                            "bm25_score": None,
                        }
                    )

            if not use_hybrid:
                if retrieval_cache_key:
                    cache_set_json(
                        key=retrieval_cache_key,
                        value=vector_results,
                        ttl_s=int(getattr(config, "CACHE_RETRIEVAL_TTL_S", 600)),
                    )
                    if should_log_cache_metrics():
                        logger.info("CACHE retrieval set key=%s", str(retrieval_cache_key)[:50])
                return vector_results

            bm25_limit = int(getattr(config, "BM25_CANDIDATES", 50))
            bm25_results = bm25_search(
                query,
                limit=bm25_limit,
                source_filter=source_filter,
                content_type_filter=content_type_filter,
            )

            metric = str(getattr(config, "VECTOR_METRIC", "COSINE")).upper()

            def vec_similarity(r: Dict[str, Any]) -> float:
                try:
                    d = float(r.get("vector_score"))
                except Exception:
                    return 0.0
                if metric == "COSINE":
                    return max(0.0, min(1.0, 1.0 - d))
                # L2: convert to bounded similarity.
                return 1.0 / (1.0 + max(0.0, d))

            vec_sims = [vec_similarity(r) for r in vector_results]
            bm25_scores = [float(r.get("bm25_score") or 0.0) for r in bm25_results]

            vec_min, vec_max = (min(vec_sims), max(vec_sims)) if vec_sims else (0.0, 0.0)
            bm_min, bm_max = (min(bm25_scores), max(bm25_scores)) if bm25_scores else (0.0, 0.0)

            def norm(x: float, lo: float, hi: float) -> float:
                if hi <= lo:
                    return 0.0
                return (x - lo) / (hi - lo)

            alpha = float(getattr(config, "HYBRID_ALPHA", 0.5))

            fused: Dict[str, Dict[str, Any]] = {}

            def key_of(r: Dict[str, Any]) -> str:
                return f"{r.get('source')}::{int(r.get('page_number') or 0)}::{int(r.get('chunk_index') or 0)}"

            for r in vector_results:
                k = key_of(r)
                r2 = dict(r)
                r2["_vec_norm"] = norm(vec_similarity(r2), vec_min, vec_max)
                r2["_bm25_norm"] = 0.0
                fused[k] = r2

            for r in bm25_results:
                k = key_of(r)
                existing = fused.get(k)
                bm = float(r.get("bm25_score") or 0.0)
                bm_norm = norm(bm, bm_min, bm_max)
                if existing is None:
                    r2 = dict(r)
                    r2.setdefault("vector_score", None)
                    r2.setdefault("score", None)
                    r2["_vec_norm"] = 0.0
                    r2["_bm25_norm"] = bm_norm
                    fused[k] = r2
                else:
                    existing["bm25_score"] = bm
                    existing["_bm25_norm"] = bm_norm

            fused_list: List[Dict[str, Any]] = []
            for r in fused.values():
                r["hybrid_score"] = (alpha * float(r.get("_vec_norm") or 0.0)) + (
                    (1.0 - alpha) * float(r.get("_bm25_norm") or 0.0)
                )
                r.pop("_vec_norm", None)
                r.pop("_bm25_norm", None)
                fused_list.append(r)

            fused_list.sort(key=lambda x: float(x.get("hybrid_score") or 0.0), reverse=True)
            final = fused_list[:candidate_limit]
            if retrieval_cache_key:
                cache_set_json(
                    key=retrieval_cache_key,
                    value=final,
                    ttl_s=int(getattr(config, "CACHE_RETRIEVAL_TTL_S", 600)),
                )
                if should_log_cache_metrics():
                    logger.info("CACHE retrieval set key=%s", str(retrieval_cache_key)[:50])
            return final

        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error searching vector database: %s", exc)
            return []

    @staticmethod
    def format_search_results(search_results: List[Dict[str, Any]]) -> str:
        """Format search results into a readable string (same as original)."""

        if not search_results:
            return "No relevant documents found."

        formatted_results: List[str] = []
        for result in search_results:
            rerank_score = result.get("rerank_score")
            if rerank_score is not None:
                # CrossEncoder outputs an unbounded logit-like score. Convert to 0..100 with sigmoid.
                match_score = (1.0 / (1.0 + math.exp(-float(rerank_score)))) * 100.0
            else:
                metric = getattr(config, "VECTOR_METRIC", "COSINE")
                score = float(result.get("score") or 0.0)
                if metric.upper() == "COSINE":
                    # For COSINE in Milvus, score is a distance (lower is better).
                    # With normalized embeddings, distance ~= 1 - cosine_similarity.
                    similarity = 1.0 - score
                    match_score = max(0.0, min(1.0, similarity)) * 100.0
                else:
                    # L2 distance is unbounded; convert to a stable 0..100 heuristic.
                    match_score = (1.0 / (1.0 + score)) * 100.0
            formatted_results.append(
                "Source: {source} ({content_type})\n"
                "Relevance: {relevance:.1f}%\n"
                "Content: {content}...\n---".format(
                    source=result["source"],
                    content_type=result["content_type"],
                    relevance=match_score,
                    content=result["text"][:200],
                )
            )

        return "\n".join(formatted_results)

    def process_query(
        self,
        query: str,
        audio_file: Optional[str] = None,
        source_filter: Optional[str] = None,
        content_type_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a query through the RAG flow and return answer + sources."""

        start_time = time.perf_counter()
        formatted_results = ""
        llm_context = ""
        sources: List[Dict[str, Any]] = []
        tool_conf: Dict[str, Any] = {}
        transcribed_query = query
        try:
            os.environ.setdefault("OPENAI_API_KEY", "ollama")
            os.environ["OPENAI_API_BASE"] = config.OLLAMA_BASE_URL
            os.environ["OPENAI_MODEL_NAME"] = config.OLLAMA_MODEL

            if audio_file:
                logger.info("🎤 Transcribing audio file...")
                transcribed_query = transcribe_audio_file(audio_file)
                logger.info("✅ Transcribed: %s", transcribed_query)
                tool_conf["transcription"] = transcription_confidence(transcribed_query).as_dict()
            else:
                transcribed_query = query
                logger.info("📝 Using text query directly: %s", transcribed_query)
                tool_conf["transcription"] = transcription_confidence(transcribed_query).as_dict()

            # Normalize the query so audio + text follow the same downstream behavior.
            # (Keep casing/punctuation for embeddings, but normalize whitespace and trim.)
            transcribed_query = " ".join(str(transcribed_query or "").strip().split())

            llm_cache_key = None
            if bool(getattr(config, "CACHE_ENABLED", True)) and bool(getattr(config, "CACHE_LLM_ENABLED", True)):
                llm_cache_key = make_cache_key(
                    prefix="llm",
                    version="v3",
                    payload={
                        "q": transcribed_query,
                        "source_filter": source_filter,
                        "content_type_filter": content_type_filter,
                        "model": str(getattr(config, "OLLAMA_MODEL", "")),
                        "temp": float(getattr(config, "LLM_TEMPERATURE", 0.1)),
                        "strict": bool(getattr(config, "STRICT_GROUNDING", True)),
                        "min_ctx": float(getattr(config, "MIN_CONTEXT_RELEVANCE", 10.0)),
                    },
                )
                cached_answer = cache_get_json(llm_cache_key)
                if isinstance(cached_answer, dict) and "answer" in cached_answer and "sources" in cached_answer:
                    if should_log_cache_metrics():
                        logger.info("CACHE llm hit key=%s", str(llm_cache_key)[:50])
                    cached_answer["latency_ms"] = int((time.perf_counter() - start_time) * 1000)
                    return cached_answer  # type: ignore[return-value]
                if should_log_cache_metrics():
                    logger.info("CACHE llm miss key=%s", str(llm_cache_key)[:50])

            def _build_sources_and_context(sr: List[Dict[str, Any]]):
                metric_local = getattr(config, "VECTOR_METRIC", "COSINE")
                min_ctx_rel_local = float(getattr(config, "MIN_CONTEXT_RELEVANCE", 10.0))
                sources_local: List[Dict[str, Any]] = []
                context_local: List[Dict[str, Any]] = []

                for r in sr:
                    if r.get("score") is None:
                        bm = float(r.get("bm25_score") or 0.0)
                        retrieval_match = (1.0 / (1.0 + math.exp(-bm))) * 100.0
                    else:
                        score = float(r.get("score") or 0.0)
                        if str(metric_local).upper() == "COSINE":
                            similarity = 1.0 - score
                            retrieval_match = max(0.0, min(1.0, similarity)) * 100.0
                        else:
                            retrieval_match = (1.0 / (1.0 + score)) * 100.0

                    if r.get("rerank_score") is not None:
                        match_score = (1.0 / (1.0 + math.exp(-float(r["rerank_score"])))) * 100.0
                    else:
                        match_score = retrieval_match

                    if match_score >= min_ctx_rel_local:
                        context_local.append(r)

                    def _safe_num(val: Any) -> Any:
                        try:
                            f = float(val)
                            return f if math.isfinite(f) else None
                        except Exception:
                            return None

                    sources_local.append(
                        {
                            "filename": r["source"],
                            "content_type": r["content_type"],
                            "relevance": match_score,
                            "retrieval_relevance": retrieval_match,
                            "text": r["text"],
                            "page_number": r.get("page_number"),
                            "timestamp_start": _safe_num(r.get("timestamp_start")),
                            "timestamp_end": _safe_num(r.get("timestamp_end")),
                            "language": r.get("language"),
                            "embedding_model": r.get("embedding_model"),
                            "ingestion_time": r.get("ingestion_time"),
                            "confidence": _safe_num(r.get("confidence")),
                            "chunk_index": r.get("chunk_index"),
                        }
                    )

                return sources_local, context_local

            # Search knowledge base (pass 1)
            search_results = self.search_vector_database(
                transcribed_query,
                source_filter=source_filter,
                content_type_filter=content_type_filter,
            )
            search_results = self._rerank_results(transcribed_query, search_results)
            top_k = int(getattr(config, "RETRIEVAL_TOP_K", 5))
            search_results = search_results[:top_k]

            sources, context_results = _build_sources_and_context(search_results)
            min_ctx_rel = float(getattr(config, "MIN_CONTEXT_RELEVANCE", 10.0))
            retr_conf = retrieval_confidence_from_sources(sources, threshold=min_ctx_rel)
            tool_conf["retrieval"] = retr_conf.as_dict()
            tool_conf["retrieval"].setdefault("meta", {})
            tool_conf["retrieval"]["meta"].update(
                {
                    "pass": 1,
                    "top_k": top_k,
                }
            )

            # Tool-confidence policy: retry retrieval with more candidates if low confidence.
            if bool(getattr(config, "TOOL_CONF_POLICY_ENABLED", True)):
                try:
                    rconf_val = float(retr_conf.confidence)
                except Exception:
                    rconf_val = 0.0

                retry_th = float(getattr(config, "RETRIEVAL_RETRY_THRESHOLD", 0.40))
                ask_th = float(getattr(config, "RETRIEVAL_ASK_FOLLOWUP_THRESHOLD", 0.25))

                if rconf_val < retry_th:
                    base_candidates = int(getattr(config, "RETRIEVAL_CANDIDATES", 20))
                    mult = int(getattr(config, "RETRIEVAL_RETRY_MULTIPLIER", 3))
                    max_cand = int(getattr(config, "RETRIEVAL_RETRY_MAX_CANDIDATES", 120))
                    retry_candidates = max(base_candidates, min(max_cand, base_candidates * max(2, mult)))

                    retry_results = self.search_vector_database(
                        transcribed_query,
                        limit=retry_candidates,
                        source_filter=source_filter,
                        content_type_filter=content_type_filter,
                    )
                    retry_results = self._rerank_results(transcribed_query, retry_results)
                    retry_results = retry_results[:top_k]

                    retry_sources, retry_context = _build_sources_and_context(retry_results)
                    retry_conf = retrieval_confidence_from_sources(retry_sources, threshold=min_ctx_rel)

                    # Keep whichever pass has higher confidence.
                    if float(retry_conf.confidence) > rconf_val:
                        sources = retry_sources
                        context_results = retry_context
                        retr_conf = retry_conf
                        tool_conf["retrieval"] = retr_conf.as_dict()
                        tool_conf["retrieval"].setdefault("meta", {})
                        tool_conf["retrieval"]["meta"].update(
                            {
                                "pass": 2,
                                "top_k": top_k,
                                "retry_candidates": retry_candidates,
                            }
                        )

                    # If still extremely low, ask a follow-up question (do not cache).
                    final_rconf = float(retr_conf.confidence)
                    if final_rconf < ask_th:
                        # Suggest near-matches to reduce user friction.
                        by_file: Dict[str, Dict[str, Any]] = {}
                        for s in (sources or []):
                            fn = str(s.get("filename") or "").strip()
                            if not fn:
                                continue
                            try:
                                rel = float(s.get("relevance") or 0.0)
                            except Exception:
                                rel = 0.0
                            entry = by_file.get(fn)
                            if entry is None:
                                by_file[fn] = {
                                    "filename": fn,
                                    "best_relevance": rel,
                                    "preview": str(s.get("text") or "")[:140].replace("\n", " ").strip(),
                                }
                            else:
                                entry["best_relevance"] = max(float(entry.get("best_relevance") or 0.0), rel)

                        suggestions = sorted(
                            by_file.values(),
                            key=lambda x: float(x.get("best_relevance") or 0.0),
                            reverse=True,
                        )[:3]

                        if suggestions:
                            lines = [
                                "I couldn't find enough relevant information to answer confidently.",
                                "Did you mean one of these documents?",
                            ]
                            for idx, s in enumerate(suggestions, start=1):
                                lines.append(
                                    f"{idx}) {s['filename']} (best match {float(s.get('best_relevance') or 0.0):.0f}%)"
                                )
                            lines.append(
                                "\nReply with the number, or tell me the exact filename, or clarify what you want to know."
                            )
                            followup = "\n".join(lines)
                        else:
                            followup = (
                                "I couldn't find enough relevant information in your knowledge base to answer confidently. "
                                "Can you clarify what exactly you want to know, or tell me which document (filename) I should use?"
                            )

                        tool_conf.setdefault("followup", {})
                        tool_conf["followup"] = {
                            "output": None,
                            "confidence": 1.0,
                            "meta": {
                                "suggested_files": suggestions,
                                "reason": "low_retrieval_confidence",
                            },
                        }
                        return {
                            "answer": followup,
                            "sources": sources,
                            "latency_ms": int((time.perf_counter() - start_time) * 1000),
                            "tool_confidence": tool_conf,
                        }

            formatted_results = self.format_search_results(search_results)

            # (sources/context_results/retrieval confidence already computed above)

            if context_results:
                llm_context = self.format_search_results(context_results)
            else:
                llm_context = "No sufficiently relevant context was retrieved."

            # Telemetry that we can persist to QueryLog.
            vector_distances: List[float] = []
            for r in (search_results or []):
                if r.get("score") is None:
                    continue
                try:
                    vector_distances.append(float(r.get("score") or 0.0))
                except Exception:
                    continue
            avg_vec_distance = (
                sum(vector_distances) / float(len(vector_distances))
                if vector_distances
                else None
            )
            retrieval_hit = bool(context_results)
            grounded = bool(getattr(config, "STRICT_GROUNDING", True)) and retrieval_hit
            not_found_msg = str(getattr(config, "NOT_FOUND_MESSAGE", "Not found in knowledge base."))

            telemetry: Dict[str, Any] = {
                "retrieval_hit": retrieval_hit,
                "avg_vector_distance": avg_vec_distance,
                "grounded": grounded,
                "retrieval_confidence": float(retr_conf.confidence),
                "retrieval_supports": int((retr_conf.meta or {}).get("supports") or 0),
            }

            if not context_results and bool(getattr(config, "STRICT_GROUNDING", True)):
                out = {
                    "answer": str(
                        getattr(config, "NOT_FOUND_MESSAGE", "Not found in knowledge base.")
                    ),
                    "sources": sources,
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "tool_confidence": tool_conf,
                    "telemetry": telemetry,
                }
                if llm_cache_key:
                    cache_set_json(
                        key=llm_cache_key,
                        value={
                            "answer": out["answer"],
                            "sources": out["sources"],
                            "latency_ms": out["latency_ms"],
                            "tool_confidence": out.get("tool_confidence"),
                        },
                        ttl_s=int(getattr(config, "CACHE_LLM_TTL_S", 90)),
                    )
                    if should_log_cache_metrics():
                        logger.info("CACHE llm set key=%s", str(llm_cache_key)[:50])
                return out

            result: str
            if bool(getattr(config, "USE_CREWAI", False)):
                try:
                    logger.info("🚀 Starting CrewAI execution...")
                    
                    # AGGRESSIVE FIX: Create agents with very high limits and explicit instructions
                    research_agent = Agent(
                        role="Knowledge Extractor",
                        goal="Extract and summarize relevant information from the provided context",
                        backstory=(
                            "You extract key information from documents. You always provide direct, "
                            "factual summaries without meta-commentary or templates."
                        ),
                        verbose=False,  # Reduce noise
                        allow_delegation=False,
                        max_iter=30,  # Very high limit
                        memory=False,
                        llm_config={
                            "model": config.OLLAMA_MODEL,
                            "base_url": config.OLLAMA_BASE_URL,
                            "temperature": 0.1,  # More deterministic
                        }
                    )

                    response_agent = Agent(
                        role="Answer Writer",
                        goal="Write clear, direct answers to user questions",
                        backstory=(
                            "You write clear, helpful answers based on provided information. "
                            "You write naturally without templates or meta-commentary."
                        ),
                        verbose=False,  # Reduce noise
                        allow_delegation=False,
                        max_iter=30,  # Very high limit
                        memory=False,
                        llm_config={
                            "model": config.OLLAMA_MODEL,
                            "base_url": config.OLLAMA_BASE_URL,
                            "temperature": 0.2,
                        }
                    )

                    # AGGRESSIVE FIX: Extremely explicit task descriptions
                    research_task = Task(
                        description=(
                            f"Read this context and extract the most relevant information:\n\n"
                            f"{llm_context}\n\n"
                            f"Question: {transcribed_query}\n\n"
                            f"Write a 2-3 sentence summary of what the context says about this question. "
                            f"Be specific and factual. Do not write 'Final Answer:' or 'my best complete final answer'."
                        ),
                        agent=research_agent,
                        expected_output="A brief factual summary (2-3 sentences)",
                    )

                    response_task = Task(
                        description=(
                            f"Question: {transcribed_query}\n\n"
                            f"Write a helpful answer using ONLY the research summary from the previous task. "
                            f"Write 3-5 sentences in a natural, conversational style. "
                            f"Do NOT write template phrases like 'Final Answer:', 'my best answer', etc. "
                            f"Just write the actual answer directly."
                        ),
                        agent=response_agent,
                        expected_output="A natural, conversational answer (3-5 sentences)",
                        context=[research_task],  # Explicitly link tasks
                    )

                    # Create crew with process control
                    crew = Crew(
                        agents=[research_agent, response_agent],
                        tasks=[research_task, response_task],
                        verbose=False,  # Less noise
                        memory=False,
                        process="sequential",  # Ensure sequential execution
                        max_rpm=100,  # No rate limiting
                    )

                    crew_result = crew.kickoff()
                    result = str(crew_result)
                    raw_result = result
                    
                    logger.info("📦 Raw CrewAI output (len=%d): %s", len(raw_result), raw_result[:200])
                    
                    # AGGRESSIVE CLEANUP
                    cleaned = raw_result.strip()
                    
                    # Remove all common template artifacts
                    bad_phrases = [
                        "final answer:",
                        "my best complete final answer to the task",
                        "my best complete final answer",
                        "my best answer",
                        "your final answer must be",
                        "the great and the most complete",
                        "it must be outcome described",
                        "i now can give a great answer",
                        "thought:",
                        "action:",
                        "action input:",
                    ]

                    cleaned_lower = cleaned.lower()
                    if "final answer:" in cleaned_lower:
                        # Keep content after the last occurrence of Final Answer:
                        cleaned = re.split(r"final answer:\s*", cleaned, flags=re.IGNORECASE)[-1].strip()
                        cleaned_lower = cleaned.lower()

                    # Non-destructive removal: delete wrapper phrases wherever they appear
                    for phrase in bad_phrases:
                        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)
                    cleaned = re.sub(r"\b(thought|action|action input)\b\s*:\s*", "", cleaned, flags=re.IGNORECASE)
                    
                    # Remove leading/trailing punctuation artifacts
                    cleaned = cleaned.strip("\"' \t\r\n.:;,- ")
                    logger.info("🧹 CrewAI cleaned output (len=%d): %s", len(cleaned), cleaned[:200])
                    
                    # STRICT quality gate - only accept substantial text
                    is_invalid = (
                        not cleaned
                        or len(cleaned) < 20  # Must be at least 20 chars
                        or cleaned.lower() in ["none", "n/a", "no answer"]
                        or "agent stopped" in cleaned.lower()
                        or cleaned.count('\n') > 20  # Too much structured output
                    )
                    
                    if is_invalid:
                        logger.warning("⚠️  CrewAI output failed quality check (len=%d): %s", 
                                      len(cleaned), cleaned[:100])
                        raise ValueError("CrewAI output unusable")
                    
                    result = cleaned
                    logger.info("✅ CrewAI success! Output length: %d chars", len(result))
                    
                except Exception as exc:
                    logger.warning("⚠️  CrewAI failed: %s - using Ollama fallback", str(exc))
                    
                    # FALLBACK: Direct Ollama call with a good prompt
                    client = OpenAI(
                        api_key=os.environ.get("OPENAI_API_KEY", "ollama"),
                        base_url=config.OLLAMA_BASE_URL,
                    )
                    
                    prompt = (
                        f"You are a helpful AI assistant. Answer the user's question using the context below.\n\n"
                        f"Context from knowledge base:\n{llm_context}\n\n"
                        f"User question: {transcribed_query}\n\n"
                        f"Instructions:\n"
                        f"- Use ONLY the context to make factual claims.\n"
                        f"- If the context is missing details needed to answer (or compare two items), say what is missing.\n"
                        f"- Do NOT invent facts or add unsupported comparisons.\n"
                        f"- Write 3-5 sentences in a natural, helpful tone\n"
                        f"- Do not include meta-commentary\n\n"
                        f"Answer:"
                    )
                    
                    completion = client.chat.completions.create(
                        model=config.OLLAMA_MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=float(getattr(config, "LLM_TEMPERATURE", 0.1)),
                        max_tokens=500,
                    )
                    result = completion.choices[0].message.content or ""
                    logger.info("✅ Ollama fallback completed")
            else:
                # Direct Ollama mode (USE_CREWAI=false)
                logger.info("🔄 Direct Ollama mode (USE_CREWAI=false)")
                client = OpenAI(
                    api_key=os.environ.get("OPENAI_API_KEY", "ollama"),
                    base_url=config.OLLAMA_BASE_URL,
                )

                completion = client.chat.completions.create(
                    model=config.OLLAMA_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Answer ONLY using the provided context. "
                                "If the answer is not present, say: 'Not found in knowledge base.'"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Context from knowledge base:\n{llm_context}\n\n"
                                f"User question: {transcribed_query}"
                            ),
                        },
                    ],
                    temperature=float(getattr(config, "LLM_TEMPERATURE", 0.1)),
                    max_tokens=500,
                )
                result = completion.choices[0].message.content or ""

            out = {
                "answer": result,
                "sources": sources,
                "latency_ms": int((time.perf_counter() - start_time) * 1000),
                "tool_confidence": tool_conf,
                "telemetry": telemetry,
            }

            # LLM confidence is bounded by retrieval confidence in grounded mode.
            try:
                rconf = float(tool_conf.get("retrieval", {}).get("confidence") or 0.0)
            except Exception:
                rconf = 0.0
            tool_conf["llm"] = llm_confidence(
                used_strict_grounding=bool(getattr(config, "STRICT_GROUNDING", True)),
                retrieval_confidence=rconf,
                answer=result,
            ).as_dict()

            # Token/cost telemetry (estimates; OpenAI usage not available with Ollama).
            prompt_tokens = _estimate_tokens(transcribed_query) + _estimate_tokens(llm_context)
            completion_tokens = _estimate_tokens(result)
            total_tokens = prompt_tokens + completion_tokens
            cost_per_1k = float(getattr(config, "LLM_COST_USD_PER_1K_TOKENS", 0.0))
            est_cost = (total_tokens / 1000.0) * max(0.0, cost_per_1k)

            hallucination_flag = False
            if bool(getattr(config, "STRICT_GROUNDING", True)):
                hallucination_flag = False
            else:
                try:
                    hallucination_flag = float(retr_conf.confidence) < 0.25 and (not_found_msg not in str(result))
                except Exception:
                    hallucination_flag = False

            telemetry.update(
                {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": est_cost,
                    "hallucination_flag": bool(hallucination_flag),
                }
            )

            if llm_cache_key:
                cache_set_json(
                    key=llm_cache_key,
                    value={
                        "answer": out["answer"],
                        "sources": out["sources"],
                        "latency_ms": out["latency_ms"],
                        "tool_confidence": out.get("tool_confidence"),
                    },
                    ttl_s=int(getattr(config, "CACHE_LLM_TTL_S", 90)),
                )
                if should_log_cache_metrics():
                    logger.info("CACHE llm set key=%s", str(llm_cache_key)[:50])

            return out
            
        except Exception as exc:
            logger.error("❌ Error generating response: %s", exc, exc_info=True)
            
            # Ultimate fallback
            preview = formatted_results[:500] if formatted_results else "(no context retrieved)"
            fallback_response = (
                f"I found some relevant information in the knowledge base, but encountered "
                f"an error generating the response. Here's what I found:\n\n{preview}"
            )
            return {
                "answer": fallback_response,
                "sources": sources,
                "latency_ms": int((time.perf_counter() - start_time) * 1000),
            }

    async def stream_response(self, query: str, audio_file: Optional[str] = None):
        """Asynchronously yield chunks of the final response for streaming."""
        result = self.process_query(query, audio_file=audio_file)
        full_response = str(result.get("answer", ""))

        for token in full_response.split():
            yield token + " "


class SearchKnowledgeBaseInput(BaseModel):
    query: str = Field(..., description="User query to search in the knowledge base")
    keywords: Optional[List[str]] = Field(
        default=None,
        description="Optional keywords provided by the agent (ignored by the backend search)",
    )
    language: Optional[str] = Field(
        default=None,
        description="Optional language hint provided by the agent (ignored by the backend search)",
    )


class SearchKnowledgeBaseTool(BaseTool):
    name: str = "Search"
    description: str = "Search the multimodal knowledge base for relevant information"
    args_schema = SearchKnowledgeBaseInput

    _service: "QueryService" = PrivateAttr()

    def __init__(self, service: QueryService) -> None:
        super().__init__()
        self._service = service

    def _run(
        self,
        query: str,
        keywords: Optional[List[str]] = None,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        logger.info("Searching knowledge base for: %s", query)
        search_results = self._service.search_vector_database(query)
        return self._service.format_search_results(search_results)


def process_query(query: str, audio_file: Optional[str] = None) -> str:
    """Module-level helper for FastAPI and other callers."""
    service = QueryService()
    result = service.process_query(query, audio_file=audio_file)
    return str(result.get("answer", ""))