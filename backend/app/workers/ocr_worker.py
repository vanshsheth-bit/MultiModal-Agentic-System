import logging
import math
import os
import time
import io
from datetime import datetime
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from app.db.postgres import SessionLocal
from app.models.database import Document
from app.core.config import config
from app.core.ingestion import _chunk_with_metadata, _detect_language
from app.core.embeddings import embed_batch
from app.core.elasticsearch_client import bulk_index_chunks
from app.core.milvus_client import get_milvus_connection
from pymilvus import Collection, utility  # type: ignore[import]

from app.core.ocr_queue import dequeue_ocr_job


logger = logging.getLogger(__name__)


def _safe_num(val: object) -> float:
    try:
        f = float(val)  # type: ignore[arg-type]
        return f if math.isfinite(f) else float("nan")
    except Exception:
        return float("nan")


def _ocr_single_pdf_page(path: Path, *, page_number_1idx: int) -> str:
    """OCR exactly one page of a PDF (1-indexed page number)."""

    try:
        from pdf2image import convert_from_path  # type: ignore[import]
        import pytesseract  # type: ignore[import]
    except Exception as exc:
        raise RuntimeError(
            "OCR dependencies not installed. Install 'pytesseract' and 'pdf2image', and ensure Tesseract + Poppler are installed."
        ) from exc

    images = convert_from_path(
        str(path),
        first_page=int(page_number_1idx),
        last_page=int(page_number_1idx),
    )
    if not images:
        return ""
    return str(pytesseract.image_to_string(images[0]) or "")


def _upsert_document_status(db: Session, doc: Document, *, status: str) -> None:
    doc.ocr_status = str(status)
    doc.ocr_updated_at = datetime.utcnow()
    db.add(doc)
    db.commit()


def _delete_existing_chunks_for_source(collection: Collection, filename: str) -> None:
    try:
        safe = str(filename).replace('\\', "\\\\").replace('"', "\\\"")
        collection.delete(expr=f'source == "{safe}"')
        collection.flush()
    except Exception as exc:
        logger.warning("⚠️ Could not delete existing chunks for %s: %s", filename, exc)


def _ingest_page_chunks_into_milvus(filename: str, chunks: List[dict]) -> int:
    get_milvus_connection()
    if not utility.has_collection(config.COLLECTION_NAME):
        raise RuntimeError("Milvus collection not initialized")

    collection = Collection(config.COLLECTION_NAME)
    collection.load()

    _delete_existing_chunks_for_source(collection, filename)

    if not chunks:
        return 0

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
        except Exception as exc:
            logger.warning("⚠️ Elasticsearch bulk index failed for OCR text: %s", exc)

    return len(chunks)


def _extract_or_ocr_pdf_to_chunks(
    *,
    path: Path,
    filename: str,
    max_pages: int,
) -> tuple[List[dict], int, int, bool]:
    """Return (chunks, pages_total, pages_processed, truncated)."""

    from PyPDF2 import PdfReader  # type: ignore[import]

    # Some PDFs trigger PyPDF2 lazy seeks while extracting text; using an in-memory
    # stream avoids "seek of closed file" errors entirely.
    raw = path.read_bytes()
    stream = io.BytesIO(raw)
    reader = PdfReader(stream)

    pages_total = len(reader.pages)
    pages_to_process = min(pages_total, int(max_pages))
    truncated = pages_total > pages_to_process

    chunks: List[dict] = []
    for page_idx in range(1, pages_to_process + 1):
        page = reader.pages[page_idx - 1]
        extracted = str(page.extract_text() or "").strip()

        # Mixed pages (text + images):
        # - keep extracted text
        # - if extracted is too short, OCR and combine (avoid losing image-only info)
        ocr_text = ""
        if len(extracted) < 50:
            ocr_text = _ocr_single_pdf_page(path, page_number_1idx=page_idx).strip()

        combined = "\n".join([t for t in [extracted, ocr_text] if t and t.strip()]).strip()
        if not combined:
            continue

        lang = _detect_language(combined)
        chunks.extend(
            _chunk_with_metadata(
                text=combined,
                source=filename,
                content_type="pdf",
                page_number=int(page_idx),
                language=str(lang),
            )
        )

    return chunks, pages_total, pages_to_process, truncated


def run_worker_forever() -> None:
    logger.info("🧾 OCR worker started")
    while True:
        job = dequeue_ocr_job(timeout_s=5)
        if not job:
            continue

        doc_id = int(job.get("doc_id") or 0)
        local_path = str(job.get("local_path") or "")
        if doc_id <= 0 or not local_path:
            continue

        path = Path(local_path)
        if not path.exists():
            logger.error("OCR job file missing: doc_id=%s path=%s", doc_id, local_path)
            continue

        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc is None:
                logger.error("OCR job document missing: doc_id=%s", doc_id)
                continue

            doc.ocr_status = "running"
            doc.ocr_error = None
            doc.ocr_pages_done = 0
            doc.ocr_updated_at = datetime.utcnow()
            db.add(doc)
            db.commit()

            max_pages = int(getattr(config, "OCR_MAX_PAGES", 25))
            max_pages = max(1, max_pages)

            t0 = time.perf_counter()
            chunks, pages_total, pages_processed, truncated = _extract_or_ocr_pdf_to_chunks(
                path=path,
                filename=str(doc.filename),
                max_pages=max_pages,
            )
            t1 = time.perf_counter()

            doc.ocr_pages_total = int(pages_total)
            doc.ocr_pages_done = int(pages_processed)
            doc.ocr_updated_at = datetime.utcnow()
            db.add(doc)
            db.commit()

            if not chunks:
                doc.ocr_status = "failed"
                doc.ocr_error = "No extractable text and OCR produced empty text"
                doc.ocr_updated_at = datetime.utcnow()
                db.add(doc)
                db.commit()
                logger.warning("OCR empty: doc_id=%s file=%s", doc_id, path.name)
                continue

            ingested_chunks = _ingest_page_chunks_into_milvus(str(doc.filename), chunks)

            doc.ocr_status = "partial" if truncated else "done"
            doc.ocr_error = None
            doc.ocr_updated_at = datetime.utcnow()
            db.add(doc)
            db.commit()

            logger.info(
                "✅ OCR done: doc_id=%s file=%s pages=%d/%d%s chunks=%d ocr_time=%.2fs",
                doc_id,
                path.name,
                pages_processed,
                pages_total,
                " (partial)" if truncated else "",
                ingested_chunks,
                (t1 - t0),
            )
        except Exception as exc:
            try:
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc is not None:
                    doc.ocr_status = "failed"
                    doc.ocr_error = str(exc)
                    doc.ocr_updated_at = datetime.utcnow()
                    db.add(doc)
                    db.commit()
            except Exception:
                pass
            logger.exception("❌ OCR job failed: doc_id=%s path=%s", doc_id, local_path)
        finally:
            db.close()


if __name__ == "__main__":
    run_worker_forever()
