"""Data ingestion and Milvus collection setup logic.

Refactored from the original ``DataIngestionFlow`` into a regular
service class while preserving behavior.
"""

import glob
import asyncio
import logging
import re
import math
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyPDF2 import PdfReader  # type: ignore[import]
from pymilvus import (  # type: ignore[import]
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    utility,
)

from .audio import transcribe_audio_file, transcribe_audio_file_detailed
from .config import config
from .embeddings import embed_batch
from .elasticsearch_client import bulk_index_chunks
from .milvus_client import get_milvus_connection, get_collection


logger = logging.getLogger(__name__)

FILE_PATTERNS = ["*.pdf", "*.mp3", "*.wav", "*.m4a", "*.flac", "*.ogg", "*.opus", "*.txt", "*.md"]
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}
TEXT_EXTENSIONS = {".txt", ".md"}


def _sentence_aware_chunks(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    text = " ".join(str(text or "").split())
    if not text:
        return []

    chunk_size = max(1, int(chunk_size or 1))
    chunk_overlap = max(0, int(chunk_overlap or 0))
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 3)

    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if s and s.strip()]
    if not sentences:
        return [text]

    chunks: List[str] = []
    current = ""

    for s in sentences:
        if not current:
            current = s
            continue

        candidate = f"{current} {s}".strip()
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        chunks.append(current)
        if chunk_overlap > 0:
            tail = current[-chunk_overlap:].strip()
            current = f"{tail} {s}".strip() if tail else s
        else:
            current = s

        if len(current) > chunk_size:
            start = 0
            while start < len(current):
                part = current[start : start + chunk_size]
                if part.strip():
                    chunks.append(part.strip())
                if chunk_overlap > 0:
                    start += max(1, chunk_size - chunk_overlap)
                else:
                    start += chunk_size
            current = ""

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _detect_language(text: str) -> str:
    try:
        from langdetect import detect  # type: ignore[import]

        sample = str(text or "").strip()
        if len(sample) > 2000:
            sample = sample[:2000]
        if not sample:
            return "und"
        return str(detect(sample))
    except Exception:
        return "und"


def _chunk_audio_words(
    *,
    words: List[Dict[str, Any]],
    source: str,
    language: str,
    embedding_model: str,
    ingestion_time: int,
) -> List[Dict[str, Any]]:
    chunk_size = int(getattr(config, "CHUNK_SIZE", 600))
    chunk_overlap = int(getattr(config, "CHUNK_OVERLAP", 120))

    # Build sentence-ish text while tracking timestamps.
    text_parts: List[str] = []
    starts: List[float] = []
    ends: List[float] = []
    confidences: List[float] = []

    chunks: List[Dict[str, Any]] = []
    chunk_index = 0

    def flush() -> None:
        nonlocal chunk_index, text_parts, starts, ends, confidences
        combined = " ".join([p for p in text_parts if str(p).strip()]).strip()
        if not combined:
            return
        ts_start = (min(starts) / 1000.0) if starts else float("nan")
        ts_end = (max(ends) / 1000.0) if ends else float("nan")
        conf = (sum(confidences) / len(confidences)) if confidences else float("nan")
        chunks.append(
            {
                "text": combined,
                "source": source,
                "content_type": "audio",
                "page_number": 0,
                "timestamp_start": float(ts_start),
                "timestamp_end": float(ts_end),
                "language": language,
                "embedding_model": embedding_model,
                "ingestion_time": ingestion_time,
                "confidence": float(conf),
                "chunk_index": int(chunk_index),
            }
        )
        chunk_index += 1

        # overlap by characters, approximate by taking last N chars from combined
        if chunk_overlap > 0:
            tail = combined[-chunk_overlap:].strip()
            text_parts = [tail] if tail else []
        else:
            text_parts = []
        starts = []
        ends = []
        confidences = []

    for w in words or []:
        token = str(w.get("text") or w.get("word") or "").strip()
        if not token:
            continue
        start_ms = w.get("start")
        end_ms = w.get("end")
        conf = w.get("confidence")

        if start_ms is not None:
            try:
                starts.append(float(start_ms))
            except Exception:
                pass
        if end_ms is not None:
            try:
                ends.append(float(end_ms))
            except Exception:
                pass
        if conf is not None:
            try:
                confidences.append(float(conf))
            except Exception:
                pass

        candidate = (" ".join(text_parts + [token])).strip()
        if len(candidate) <= chunk_size:
            text_parts.append(token)
            continue

        flush()
        text_parts.append(token)

    flush()
    return chunks


def _chunk_with_metadata(
    *,
    text: str,
    source: str,
    content_type: str,
    page_number: int = 0,
    timestamp_start: float = float("nan"),
    timestamp_end: float = float("nan"),
    language: str = "unknown",
    confidence: float = float("nan"),
) -> List[Dict[str, Any]]:
    chunk_size = int(getattr(config, "CHUNK_SIZE", 600))
    chunk_overlap = int(getattr(config, "CHUNK_OVERLAP", 120))
    ingestion_time = int(datetime.utcnow().timestamp())
    embedding_model = str(getattr(config, "EMBEDDING_MODEL", ""))

    chunks: List[Dict[str, Any]] = []
    for idx, chunk_text in enumerate(
        _sentence_aware_chunks(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    ):
        if not str(chunk_text or "").strip():
            continue
        chunks.append(
            {
                "text": chunk_text,
                "source": source,
                "content_type": content_type,
                "page_number": int(page_number),
                "timestamp_start": float(timestamp_start),
                "timestamp_end": float(timestamp_end),
                "language": str(language or "unknown"),
                "embedding_model": embedding_model,
                "ingestion_time": ingestion_time,
                "confidence": float(confidence),
                "chunk_index": int(idx),
            }
        )
    return chunks


def _extract_text_from_path(path: Path) -> tuple[str, str]:
    """Extract text + content_type from a supported file path."""

    if path.suffix.lower() == ".pdf":
        with path.open("rb") as f:
            reader = PdfReader(f)
            extracted_pages: List[str] = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_pages.append(page_text)
            text = "\n".join(extracted_pages)
        if not text.strip():
            if bool(getattr(config, "OCR_ENABLED", False)):
                try:
                    logger.info("🔎 Running OCR for scanned PDF: %s", path.name)
                    text = _ocr_pdf(path)
                except Exception as exc:
                    logger.warning("⚠️ OCR failed for %s: %s", path.name, exc)
        return text, "pdf"

    if path.suffix.lower() in AUDIO_EXTENSIONS:
        return transcribe_audio_file(str(path)), "audio"

    if path.suffix.lower() in TEXT_EXTENSIONS:
        with path.open("r", encoding="utf-8") as f:
            return f.read(), "text"

    raise ValueError(f"Unsupported file type: {path.suffix}")


def ingest_single_file(file_path: str) -> dict:
    """Ingest a single file into Milvus.

    This is designed for ingest-on-upload so that newly uploaded files become
    searchable without requiring a full /admin/reindex.
    """

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    get_milvus_connection()
    if not utility.has_collection(config.COLLECTION_NAME):
        service = IngestionService()
        service.setup_vector_database()
    collection = Collection(config.COLLECTION_NAME)
    collection.load()

    filename = path.name
    logger.info("📥 Ingesting single file: %s", filename)

    # Best-effort idempotency: delete old chunks for this filename.
    try:
        safe_name = filename.replace('\\', "\\\\").replace('"', "\\\"")
        collection.delete(expr=f'source == "{safe_name}"')
        collection.flush()
    except Exception as exc:  # pragma: no cover
        logger.warning("⚠️ Could not delete existing vectors for %s: %s", filename, exc)

    content_type: str
    chunks: List[Dict[str, Any]] = []
    if path.suffix.lower() == ".pdf":
        with path.open("rb") as f:
            reader = PdfReader(f)
            for page_idx, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if not page_text.strip() and bool(getattr(config, "OCR_ENABLED", False)):
                    try:
                        logger.info("🔎 Running OCR for scanned PDF: %s (page=%d)", filename, page_idx)
                        page_text = _ocr_pdf(path)
                    except Exception as exc:
                        logger.warning("⚠️ OCR failed for %s (page=%d): %s", filename, page_idx, exc)
                if page_text.strip():
                    chunks.extend(
                        _chunk_with_metadata(
                            text=page_text,
                            source=filename,
                            content_type="pdf",
                            page_number=page_idx,
                            language=_detect_language(page_text),
                        )
                    )
        content_type = "pdf"
    else:
        if path.suffix.lower() in AUDIO_EXTENSIONS:
            detailed = transcribe_audio_file_detailed(str(path))
            text = str(detailed.get("text") or "").strip()
            if not text:
                raise ValueError(f"Transcription returned empty text for {filename}")
            language = str(detailed.get("language_code") or "").strip() or _detect_language(text)
            ingestion_time = int(datetime.utcnow().timestamp())
            embedding_model = str(getattr(config, "EMBEDDING_MODEL", ""))
            words = detailed.get("words") or []
            if not isinstance(words, list) or not words:
                raise RuntimeError(
                    "AssemblyAI did not return word timestamps; cannot produce real audio timestamps"
                )
            chunks = _chunk_audio_words(
                words=words,
                source=filename,
                language=language,
                embedding_model=embedding_model,
                ingestion_time=ingestion_time,
            )
            content_type = "audio"
        else:
            text, content_type = _extract_text_from_path(path)
            if not str(text or "").strip():
                raise ValueError(f"No extractable text from {filename}")
            chunks = _chunk_with_metadata(
                text=text,
                source=filename,
                content_type=content_type,
                language=_detect_language(text),
            )

    embeddings = embed_batch([c["text"] for c in chunks])
    data = [
        [c["text"] for c in chunks],
        [c["source"] for c in chunks],
        [c["content_type"] for c in chunks],
        [c["page_number"] for c in chunks],
        [c["timestamp_start"] for c in chunks],
        [c["timestamp_end"] for c in chunks],
        [c["language"] for c in chunks],
        [c["embedding_model"] for c in chunks],
        [c["ingestion_time"] for c in chunks],
        [c["confidence"] for c in chunks],
        [c["chunk_index"] for c in chunks],
        embeddings,
    ]
    collection.insert(data)
    collection.flush()

    if bool(getattr(config, "HYBRID_SEARCH_ENABLED", True)):
        try:
            bulk_index_chunks(chunks)
        except Exception as exc:  # pragma: no cover
            logger.warning("⚠️ Elasticsearch bulk index failed for %s: %s", filename, exc)

    return {"status": "ok", "filename": filename, "chunks": len(chunks), "content_type": content_type}


def ingest_single_file_safe(file_path: str) -> dict:
    """Wrapper for ingest_single_file that logs exceptions for BackgroundTasks."""

    try:
        logger.info("🚀 Starting background ingestion for: %s", file_path)
        result = ingest_single_file(file_path)
        logger.info("✅ Background ingestion completed: %s", result)
        return result
    except Exception as exc:  # pragma: no cover
        logger.exception("❌ ingest_single_file failed for %s: %s", file_path, exc)
        try:
            error_log_path = Path(file_path).parent / "ingestion_errors.log"
            with error_log_path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()}: Failed to ingest {file_path}: {exc}\n")
        except Exception:
            logger.exception("❌ Failed writing ingestion error log")
        return {"status": "error", "file_path": file_path, "error": str(exc)}


def _ocr_pdf(path: Path) -> str:
    try:
        from pdf2image import convert_from_path  # type: ignore[import]
        import pytesseract  # type: ignore[import]
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "OCR dependencies not installed. Install 'pytesseract' and 'pdf2image', "
            "and ensure Tesseract + Poppler are installed on the system."
        ) from exc

    images = convert_from_path(str(path))
    extracted_pages: List[str] = []
    for image in images:
        page_text = pytesseract.image_to_string(image) or ""
        if page_text.strip():
            extracted_pages.append(page_text)
    return "\n".join(extracted_pages)


@dataclass
class DataIngestionState:
    """State container mirroring the original DataIngestionState."""

    collection: Optional[Collection] = None
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    processed_files: List[str] = field(default_factory=list)
    discovered_files: List[str] = field(default_factory=list)


class IngestionService:
    """Service encapsulating the ingestion flow steps.

    Methods are intentionally close to the original Flow steps to make
    behavior identical while removing Flow-specific decorators.
    """

    def __init__(self) -> None:
        self.state = DataIngestionState()

    def discover_files(self) -> DataIngestionState:
        """Discover all files in the data directory (same logic)."""

        logger.info("🔍 Discovering files in data directory...")
        data_dir = Path(config.DATA_DIR)

        if not data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {data_dir}")

        discovered_files: List[str] = []
        for pattern in FILE_PATTERNS:
            # Top-level files (backwards compatible)
            discovered_files.extend(glob.glob(str(data_dir / pattern)))

            # Recursively include uploads (e.g. data/uploads/anonymous/*.pdf) and any other
            # nested data folders.
            discovered_files.extend(
                glob.glob(
                    str(data_dir / "**" / pattern),
                    recursive=True,
                )
            )

        discovered_files = sorted(list(set(discovered_files)))
        logger.info("📁 Discovered %d files", len(discovered_files))
        self.state.discovered_files = discovered_files
        return self.state

    def setup_vector_database(self) -> DataIngestionState:
        """Initialize Milvus connection and collection (same schema)."""

        logger.info("🔧 Setting up vector database...")
        get_milvus_connection()

        if not utility.has_collection(config.COLLECTION_NAME):
            fields = [
                FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema("text", DataType.VARCHAR, max_length=65535),
                FieldSchema("source", DataType.VARCHAR, max_length=255),
                FieldSchema("content_type", DataType.VARCHAR, max_length=50),
                FieldSchema("page_number", DataType.INT64),
                FieldSchema("timestamp_start", DataType.FLOAT),
                FieldSchema("timestamp_end", DataType.FLOAT),
                FieldSchema("language", DataType.VARCHAR, max_length=32),
                FieldSchema("embedding_model", DataType.VARCHAR, max_length=255),
                FieldSchema("ingestion_time", DataType.INT64),
                FieldSchema("confidence", DataType.FLOAT),
                FieldSchema("chunk_index", DataType.INT64),
                FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=config.EMBEDDING_DIM),
            ]
            schema = CollectionSchema(fields, "Multimodal RAG collection")
            collection = Collection(config.COLLECTION_NAME, schema)
            collection.create_index(
                "embedding",
                {
                    "index_type": getattr(config, "VECTOR_INDEX_TYPE", "IVF_FLAT"),
                    "metric_type": getattr(config, "VECTOR_METRIC", "COSINE"),
                    "params": {"nlist": int(getattr(config, "VECTOR_NLIST", 1024))},
                },
            )
            logger.info("✅ Collection created and indexed")
        else:
            logger.info("✅ Collection already exists")
            collection = Collection(config.COLLECTION_NAME)

        collection.load()
        logger.info("✅ Vector database setup completed")
        self.state.collection = collection
        return self.state

    def process_multimodal_data(self) -> DataIngestionState:
        """Process discovered files from the data directory."""

        if self.state.collection is None:
            raise ValueError("Collection must be initialized before processing data")

        logger.info("📄 Processing %d discovered files...", len(self.state.discovered_files))

        chunks: List[Dict[str, Any]] = []
        processed_files: List[str] = []

        for file_path in self.state.discovered_files:
            path = Path(file_path)
            filename = path.name
            logger.info("🔄 Processing: %s", filename)

            try:
                if path.suffix.lower() == ".pdf":
                    with path.open("rb") as f:
                        reader = PdfReader(f)
                        for page_idx, page in enumerate(reader.pages, start=1):
                            page_text = page.extract_text() or ""
                            if not page_text.strip() and bool(getattr(config, "OCR_ENABLED", False)):
                                try:
                                    logger.info("🔎 Running OCR for scanned PDF: %s (page=%d)", filename, page_idx)
                                    page_text = _ocr_pdf(path)
                                except Exception as exc:
                                    logger.warning(
                                        "⚠️ OCR failed for %s (page=%d): %s",
                                        filename,
                                        page_idx,
                                        exc,
                                    )
                            if page_text.strip():
                                chunks.extend(
                                    _chunk_with_metadata(
                                        text=page_text,
                                        source=filename,
                                        content_type="pdf",
                                        page_number=page_idx,
                                        language=_detect_language(page_text),
                                    )
                                )
                    content_type = "pdf"
                elif path.suffix.lower() in AUDIO_EXTENSIONS:
                    detailed = transcribe_audio_file_detailed(str(path))
                    text = str(detailed.get("text") or "").strip()
                    if not text:
                        raise ValueError(f"Transcription returned empty text for {filename}")
                    language = str(detailed.get("language_code") or "").strip() or _detect_language(text)
                    ingestion_time = int(datetime.utcnow().timestamp())
                    embedding_model = str(getattr(config, "EMBEDDING_MODEL", ""))
                    words = detailed.get("words") or []
                    if not isinstance(words, list) or not words:
                        raise RuntimeError(
                            "AssemblyAI did not return word timestamps; cannot produce real audio timestamps"
                        )
                    chunks.extend(
                        _chunk_audio_words(
                            words=words,
                            source=filename,
                            language=language,
                            embedding_model=embedding_model,
                            ingestion_time=ingestion_time,
                        )
                    )
                    content_type = "audio"
                elif path.suffix.lower() in TEXT_EXTENSIONS:
                    with path.open("r", encoding="utf-8") as f:
                        text = f.read()
                    content_type = "text"
                else:
                    logger.warning("⚠️ Skipping unsupported file: %s", filename)
                    continue

                if content_type != "pdf":
                    if not text.strip():
                        logger.warning(
                            "⚠️ No extractable text found in %s (it may be scanned/image-based)",
                            filename,
                        )
                        continue
                    chunks.extend(
                        _chunk_with_metadata(
                            text=text,
                            source=filename,
                            content_type=content_type,
                            language=_detect_language(text),
                        )
                    )

                processed_files.append(filename)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("❌ Error processing %s: %s", filename, exc)
                continue

        self.state.chunks = chunks
        self.state.processed_files = processed_files
        return self.state

    def _process_file_to_chunks(self, file_path: str) -> tuple[str, List[Dict[str, Any]]]:
        path = Path(file_path)
        filename = path.name

        chunks: List[Dict[str, Any]] = []
        content_type: str
        text: str = ""

        if path.suffix.lower() == ".pdf":
            with path.open("rb") as f:
                reader = PdfReader(f)
                for page_idx, page in enumerate(reader.pages, start=1):
                    page_text = page.extract_text() or ""
                    if not page_text.strip() and bool(getattr(config, "OCR_ENABLED", False)):
                        try:
                            logger.info(
                                "🔎 Running OCR for scanned PDF: %s (page=%d)",
                                filename,
                                page_idx,
                            )
                            page_text = _ocr_pdf(path)
                        except Exception as exc:
                            logger.warning(
                                "⚠️ OCR failed for %s (page=%d): %s",
                                filename,
                                page_idx,
                                exc,
                            )
                    if page_text.strip():
                        chunks.extend(
                            _chunk_with_metadata(
                                text=page_text,
                                source=filename,
                                content_type="pdf",
                                page_number=page_idx,
                                language=_detect_language(page_text),
                            )
                        )
            content_type = "pdf"
            return content_type, chunks

        if path.suffix.lower() in AUDIO_EXTENSIONS:
            detailed = transcribe_audio_file_detailed(str(path))
            text = str(detailed.get("text") or "").strip()
            if not text:
                raise ValueError(f"Transcription returned empty text for {filename}")
            language = str(detailed.get("language_code") or "").strip() or _detect_language(text)
            ingestion_time = int(datetime.utcnow().timestamp())
            embedding_model = str(getattr(config, "EMBEDDING_MODEL", ""))
            words = detailed.get("words") or []
            if not isinstance(words, list) or not words:
                raise RuntimeError(
                    "AssemblyAI did not return word timestamps; cannot produce real audio timestamps"
                )
            chunks = _chunk_audio_words(
                words=words,
                source=filename,
                language=language,
                embedding_model=embedding_model,
                ingestion_time=ingestion_time,
            )
            content_type = "audio"
            return content_type, chunks

        if path.suffix.lower() in TEXT_EXTENSIONS:
            with path.open("r", encoding="utf-8") as f:
                text = f.read()
            content_type = "text"
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")

        if not text.strip():
            return content_type, []

        chunks = _chunk_with_metadata(
            text=text,
            source=filename,
            content_type=content_type,
            language=_detect_language(text),
        )
        return content_type, chunks

    async def _embed_chunks_async(
        self,
        chunks: List[Dict[str, Any]],
        *,
        embed_sem: asyncio.Semaphore,
    ) -> List[Dict[str, Any]]:
        if not chunks:
            return []

        batch_size = int(getattr(config, "EMBED_BATCH_SIZE", 128))
        batch_size = max(1, batch_size)

        async def embed_one_batch(batch: List[Dict[str, Any]]) -> List[List[float]]:
            async with embed_sem:
                texts = [c["text"] for c in batch]
                return await asyncio.to_thread(embed_batch, texts)

        tasks: List[asyncio.Task[List[List[float]]]] = []
        batches: List[List[Dict[str, Any]]] = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            batches.append(batch)
            tasks.append(asyncio.create_task(embed_one_batch(batch)))

        batch_embeddings = await asyncio.gather(*tasks)
        flat_embeddings: List[List[float]] = []
        for be in batch_embeddings:
            flat_embeddings.extend(be)

        updated: List[Dict[str, Any]] = []
        for chunk, embedding in zip(chunks, flat_embeddings):
            c = dict(chunk)
            c["embedding"] = embedding
            updated.append(c)
        return updated

    async def ingest_files_parallel(self) -> Dict[str, Any]:
        """Parallel ingestion optimized for large corpora.

        - Processes files concurrently (extract/chunk/transcribe)
        - Generates embeddings concurrently in bounded batches
        - Inserts into Milvus under a lock (Milvus client is not thread-safe)
        - Flushes once at the end
        """

        if self.state.collection is None:
            raise ValueError("Collection must be initialized before processing data")

        files = list(self.state.discovered_files or [])
        overall_start = time.perf_counter()
        logger.info("⚡ Parallel ingest: %d files", len(files))

        file_concurrency = int(getattr(config, "INGEST_FILE_CONCURRENCY", 4))
        file_concurrency = max(1, file_concurrency)
        embed_concurrency = int(getattr(config, "EMBED_CONCURRENCY", 1))
        embed_concurrency = max(1, embed_concurrency)

        file_sem = asyncio.Semaphore(file_concurrency)
        embed_sem = asyncio.Semaphore(embed_concurrency)
        insert_lock = asyncio.Lock()

        processed_files: List[str] = []
        discovered_files = len(files)
        total_chunks = 0

        total_extract_s = 0.0
        total_embed_s = 0.0
        total_insert_s = 0.0

        async def handle_one(file_path: str) -> None:
            nonlocal total_chunks, total_extract_s, total_embed_s, total_insert_s
            path = Path(file_path)
            filename = path.name
            file_start = time.perf_counter()
            logger.info("⏳ Start: %s", filename)
            async with file_sem:
                try:
                    t0 = time.perf_counter()
                    content_type, chunks = await asyncio.to_thread(self._process_file_to_chunks, file_path)
                    t1 = time.perf_counter()
                    total_extract_s += (t1 - t0)
                    if not chunks:
                        logger.warning("⚠️ No chunks produced for %s", filename)
                        return

                    t2 = time.perf_counter()
                    chunks_with_emb = await self._embed_chunks_async(chunks, embed_sem=embed_sem)
                    t3 = time.perf_counter()
                    total_embed_s += (t3 - t2)

                    async with insert_lock:
                        t4 = time.perf_counter()
                        data = [
                            [c["text"] for c in chunks_with_emb],
                            [c["source"] for c in chunks_with_emb],
                            [c["content_type"] for c in chunks_with_emb],
                            [c["page_number"] for c in chunks_with_emb],
                            [c["timestamp_start"] for c in chunks_with_emb],
                            [c["timestamp_end"] for c in chunks_with_emb],
                            [c["language"] for c in chunks_with_emb],
                            [c["embedding_model"] for c in chunks_with_emb],
                            [c["ingestion_time"] for c in chunks_with_emb],
                            [c["confidence"] for c in chunks_with_emb],
                            [c["chunk_index"] for c in chunks_with_emb],
                            [c["embedding"] for c in chunks_with_emb],
                        ]
                        self.state.collection.insert(data)
                        t5 = time.perf_counter()
                        total_insert_s += (t5 - t4)

                    if bool(getattr(config, "HYBRID_SEARCH_ENABLED", True)):
                        try:
                            bulk_index_chunks(chunks)
                        except Exception as exc:  # pragma: no cover
                            logger.warning("⚠️ Elasticsearch bulk index failed for %s: %s", filename, exc)

                    processed_files.append(filename)
                    total_chunks += len(chunks)
                    elapsed = time.perf_counter() - file_start
                    logger.info(
                        "✅ Ingested %s (%s, chunks=%d, %.2fs)",
                        filename,
                        content_type,
                        len(chunks),
                        elapsed,
                    )
                except Exception as exc:
                    elapsed = time.perf_counter() - file_start
                    logger.error("❌ Failed ingesting %s (%.2fs): %s", filename, elapsed, exc)

        await asyncio.gather(*(handle_one(fp) for fp in files))

        flush_start = time.perf_counter()
        try:
            self.state.collection.flush()
        except Exception as exc:  # pragma: no cover
            logger.warning("⚠️ Milvus flush failed after parallel ingest: %s", exc)
        flush_s = time.perf_counter() - flush_start

        self.state.processed_files = processed_files
        overall_elapsed = time.perf_counter() - overall_start
        fps = (len(processed_files) / overall_elapsed) if overall_elapsed > 0 else 0.0
        cps = (float(total_chunks) / overall_elapsed) if overall_elapsed > 0 else 0.0
        logger.info(
            "🏁 Parallel ingest done: processed=%d/%d files, chunks=%d, elapsed=%.2fs (%.2f files/s, %.2f chunks/s)",
            len(processed_files),
            discovered_files,
            int(total_chunks),
            overall_elapsed,
            fps,
            cps,
        )
        return {
            "status": "ok",
            "discovered_files": discovered_files,
            "processed_files": len(processed_files),
            "chunks": int(total_chunks),
            "elapsed_s": float(overall_elapsed),
            "timings_s": {
                "extract_chunk_total": float(total_extract_s),
                "embed_total": float(total_embed_s),
                "milvus_insert_total": float(total_insert_s),
                "milvus_flush": float(flush_s),
            },
        }

    def generate_embeddings(self) -> DataIngestionState:
        """Generate embeddings for processed chunks (same batching)."""

        logger.info("🧠 Generating embeddings for %d chunks...", len(self.state.chunks))

        texts = [chunk["text"] for chunk in self.state.chunks]
        # Preserve original batching behavior (100 at a time)
        batch_size = 100
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_embeddings = embed_batch(batch_texts)
            all_embeddings.extend(batch_embeddings)

        updated_chunks: List[Dict[str, Any]] = []
        for chunk, embedding in zip(self.state.chunks, all_embeddings):
            chunk_copy = dict(chunk)
            chunk_copy["embedding"] = embedding
            updated_chunks.append(chunk_copy)

        self.state.chunks = updated_chunks
        logger.info("✅ Embeddings generation completed")
        return self.state

    def store_in_vector_database(self) -> DataIngestionState:
        """Insert processed chunks into Milvus (same logic)."""

        if self.state.collection is None:
            raise ValueError("Collection must be initialized before storing data")

        logger.info("💾 Inserting %d chunks into vector database...", len(self.state.chunks))

        data = [
            [chunk["text"] for chunk in self.state.chunks],
            [chunk["source"] for chunk in self.state.chunks],
            [chunk["content_type"] for chunk in self.state.chunks],
            [chunk["page_number"] for chunk in self.state.chunks],
            [chunk["timestamp_start"] for chunk in self.state.chunks],
            [chunk["timestamp_end"] for chunk in self.state.chunks],
            [chunk["language"] for chunk in self.state.chunks],
            [chunk["embedding_model"] for chunk in self.state.chunks],
            [chunk["ingestion_time"] for chunk in self.state.chunks],
            [chunk["confidence"] for chunk in self.state.chunks],
            [chunk["chunk_index"] for chunk in self.state.chunks],
            [chunk["embedding"] for chunk in self.state.chunks],
        ]

        self.state.collection.insert(data)
        self.state.collection.flush()
        if bool(getattr(config, "HYBRID_SEARCH_ENABLED", True)):
            try:
                bulk_index_chunks(self.state.chunks)
            except Exception as exc:  # pragma: no cover
                logger.warning("⚠️ Elasticsearch bulk index failed during reindex: %s", exc)
        logger.info("✅ Data insertion completed")
        return self.state


def run_full_ingestion_pipeline() -> DataIngestionState:
    """Convenience wrapper to run the full ingestion pipeline."""

    service = IngestionService()
    service.discover_files()
    service.setup_vector_database()
    service.process_multimodal_data()
    if not service.state.chunks:
        return service.state
    service.generate_embeddings()
    return service.store_in_vector_database()


def check_system_status() -> bool:
    """Check if the system is ready (equivalent to original check_system_status)."""

    try:
        # Check Milvus connection
        get_milvus_connection()

        # Check if collection exists and has data
        if utility.has_collection(config.COLLECTION_NAME):
            collection = get_collection()
            collection.load()
            if int(getattr(collection, "num_entities", 0) or 0) > 0:
                logger.info("✅ System ready with data")
                return True
            logger.info("⚠️ Collection exists but is empty")
            return False
        logger.info("⚠️ Collection does not exist")
        return False
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("❌ System check failed: %s", exc)
        return False
