"""Application settings using Pydantic BaseSettings.

This module defines a ``Settings`` object for the new backend code while
also exposing a ``config`` alias so existing imports within this
repository keep working. The original top-level ``config.py`` used by
the legacy CLI remains untouched and is not affected by this module.
"""

from pathlib import Path

from pydantic_settings import BaseSettings


_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # Existing settings (mirroring the original config.py)
    ASSEMBLYAI_API_KEY: str = ""
    ASSEMBLYAI_BASE_URL: str = "https://api.assemblyai.com"
    ASSEMBLYAI_SPEECH_MODEL: str = "universal-2"
    OPENAI_API_KEY: str = ""
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    COLLECTION_NAME: str = "multimodal_rag"
    EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_DEVICE: str = "auto"
    DATA_DIR: str = str(_REPO_ROOT / "data")

    # Ingestion / chunking
    CHUNK_SIZE: int = 600
    CHUNK_OVERLAP: int = 120
    OCR_ENABLED: bool = False

    INGEST_FILE_CONCURRENCY: int = 4
    EMBED_BATCH_SIZE: int = 128
    EMBED_CONCURRENCY: int = 1

    # Retrieval
    RETRIEVAL_CANDIDATES: int = 20
    RETRIEVAL_TOP_K: int = 5

    # Hybrid retrieval (Elasticsearch BM25 + Milvus vector)
    HYBRID_SEARCH_ENABLED: bool = True
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    ELASTICSEARCH_INDEX: str = "multimodal_rag_chunks"
    BM25_CANDIDATES: int = 50
    HYBRID_ALPHA: float = 0.5

    # Context quality / grounding
    # Retrieved chunks with very low relevance tend to cause hallucinated comparisons.
    # This threshold is applied when building the LLM context (sources are still returned).
    MIN_CONTEXT_RELEVANCE: float = 10.0

    # Deterministic grounding
    # When enabled, the system will not call the LLM unless it has retrieved sufficiently
    # relevant context. This is the main guardrail to prevent hallucinations.
    STRICT_GROUNDING: bool = True
    NOT_FOUND_MESSAGE: str = "Not found in knowledge base."

    # Optional reranker (CrossEncoder)
    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    CACHE_RERANK_ENABLED: bool = True
    CACHE_RERANK_TTL_S: int = 24 * 60 * 60

    # Tool-confidence based controller policy
    # If retrieval confidence is below RETRIEVAL_RETRY_THRESHOLD, retry retrieval with more candidates.
    TOOL_CONF_POLICY_ENABLED: bool = True
    RETRIEVAL_RETRY_THRESHOLD: float = 0.40
    RETRIEVAL_ASK_FOLLOWUP_THRESHOLD: float = 0.25
    RETRIEVAL_RETRY_MULTIPLIER: int = 3
    RETRIEVAL_RETRY_MAX_CANDIDATES: int = 120

    # Vector search configuration
    # - L2: Euclidean distance
    # - COSINE: cosine distance (1 - cosine similarity)
    VECTOR_METRIC: str = "COSINE"
    VECTOR_INDEX_TYPE: str = "IVF_FLAT"
    VECTOR_NLIST: int = 1024

    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434/v1"
    OLLAMA_MODEL: str = "llama3.1"

    # LLM generation
    LLM_TEMPERATURE: float = 0.1

    # Telemetry / cost estimation
    LLM_COST_USD_PER_1K_TOKENS: float = 0.0

    CACHE_ENABLED: bool = True

    CACHE_EMBEDDINGS_ENABLED: bool = True
    CACHE_RETRIEVAL_ENABLED: bool = True
    CACHE_LLM_ENABLED: bool = True

    CACHE_EMBEDDINGS_TTL_S: int = 7 * 24 * 60 * 60

    CACHE_RETRIEVAL_TTL_S: int = 600
    CACHE_LLM_TTL_S: int = 90

    # Debugging
    LOG_TRANSCRIPTS: bool = False
    TRANSCRIPT_LOG_CHARS: int = 400

    USE_CREWAI: bool = False

    # New settings for backend infrastructure
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    REDIS_URL: str = "redis://localhost:6379/0"

    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "documents"

    JWT_SECRET: str = "change-me-in-production"
    JWT_REFRESH_SECRET: str = "change-me-in-production-refresh"
    JWT_ALGORITHM: str = "HS256"

    # Observability
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "development"

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = str(_REPO_ROOT / ".env")


settings = Settings()

# Backwards-compatible alias used by previously written backend modules
config = settings
