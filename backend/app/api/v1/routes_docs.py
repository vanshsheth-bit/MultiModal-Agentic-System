from datetime import datetime
import logging
from pathlib import Path
from typing import List, Optional
import math

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from botocore.exceptions import ClientError
from openai import OpenAI
from pymilvus import Collection, utility  # type: ignore[import]
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.postgres import SessionLocal
from app.db.s3 import get_s3_bucket_name, get_s3_client
from app.models.database import Document
from app.core.config import config
from app.core.ingestion import ingest_single_file_safe
from app.core.milvus_client import get_milvus_connection
from app.core.query import QueryService
from app.models.responses import QueryResponse
from app.core.ocr_queue import enqueue_ocr_job


logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


def _infer_content_type_from_ext(file_ext: str) -> str:
    ext = str(file_ext or "").lower().strip()
    if ext == ".pdf":
        return "pdf"
    if ext in {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}:
        return "audio"
    if ext in {".txt", ".md"}:
        return "text"
    return "unknown"


def _looks_scanned_pdf(path: Path) -> tuple[bool, int]:
    """Heuristic: if most pages have no extractable text, treat as scanned."""

    try:
        from PyPDF2 import PdfReader  # type: ignore[import]

        with path.open("rb") as f:
            reader = PdfReader(f)
            pages = list(reader.pages)
            total = len(pages)
            if total <= 0:
                return True, 0

            empty = 0
            for p in pages:
                txt = (p.extract_text() or "").strip()
                if len(txt) < 20:
                    empty += 1

            # scanned if >= 60% pages are empty-ish
            return (empty / float(total)) >= 0.6, total
    except Exception:
        return False, 0


def _get_db() -> Session:
    return SessionLocal()


def _get_query_service() -> QueryService:
    return QueryService()


@router.post("/upload")
async def upload_documents(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)) -> dict:
    """Save documents to local storage (default) or S3 when configured."""

    s3 = get_s3_client()
    bucket = get_s3_bucket_name()
    db = _get_db()

    uploads_dir = Path(config.DATA_DIR) / "uploads" / "anonymous"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    uploaded: list[dict] = []
    try:
        for f in files:
            file_ext = Path(f.filename).suffix.lower()
            supported_extensions = {
                ".pdf",
                ".mp3",
                ".wav",
                ".m4a",
                ".flac",
                ".ogg",
                ".opus",
                ".txt",
                ".md",
            }
            if file_ext not in supported_extensions:
                logger.warning("⚠️ Unsupported file type uploaded: %s", f.filename)
                uploaded.append(
                    {
                        "filename": f.filename,
                        "storage_uri": "error",
                        "ingest": "failed",
                        "error": f"Unsupported file type: {file_ext}",
                    }
                )
                continue

            key = f"anonymous/{f.filename}"
            content = await f.read()

            if len(content) == 0:
                logger.warning("⚠️ Empty file uploaded: %s", f.filename)
                uploaded.append(
                    {
                        "filename": f.filename,
                        "storage_uri": "error",
                        "ingest": "failed",
                        "error": "Empty file",
                    }
                )
                continue

            storage_uri: str
            local_ingest_path: str | None = None
            use_s3 = bool(config.S3_ACCESS_KEY and config.S3_SECRET_KEY and config.S3_ENDPOINT and bucket)
            if use_s3:
                try:
                    s3.put_object(Bucket=bucket, Key=key, Body=content)
                    storage_uri = key
                    # Still write a local copy so we can ingest/transcribe immediately.
                    local_path = uploads_dir / f.filename
                    local_path.write_bytes(content)
                    local_ingest_path = str(local_path)
                except ClientError as exc:
                    error_code = str(exc.response.get("Error", {}).get("Code", ""))
                    if error_code in {"NoSuchBucket", "404"}:
                        local_path = uploads_dir / f.filename
                        local_path.write_bytes(content)
                        storage_uri = f"local://{local_path.as_posix()}"
                        local_ingest_path = str(local_path)
                    else:
                        raise
            else:
                local_path = uploads_dir / f.filename
                local_path.write_bytes(content)
                storage_uri = f"local://{local_path.as_posix()}"
                local_ingest_path = str(local_path)

            inferred_type = _infer_content_type_from_ext(file_ext)

            doc = Document(
                owner_id=1,  # placeholder; auth-backed ownership can be wired later
                filename=f.filename,
                storage_uri=storage_uri,
                content_type=inferred_type,
                created_at=datetime.utcnow(),
                ocr_status="not_needed",
                ocr_pages_total=None,
                ocr_pages_done=None,
                ocr_error=None,
                ocr_updated_at=None,
            )
            db.add(doc)

            # Flush so we get doc.id for queue payload before commit.
            db.flush()

            if local_ingest_path:
                audio_extensions = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"}
                if file_ext in audio_extensions:
                    logger.info("🎤 Audio file detected, testing transcription: %s", f.filename)
                    try:
                        from app.core.audio import transcribe_audio_file

                        test_transcript = transcribe_audio_file(local_ingest_path)
                        logger.info(
                            "✅ Transcription test successful: %s (length: %d chars)",
                            f.filename,
                            len(test_transcript),
                        )
                        background_tasks.add_task(ingest_single_file_safe, local_ingest_path)
                        preview = test_transcript
                        if len(preview) > 100:
                            preview = preview[:100] + "..."
                        uploaded.append(
                            {
                                "filename": f.filename,
                                "storage_uri": storage_uri,
                                "ingest": "queued",
                                "transcription_preview": preview,
                            }
                        )
                    except Exception as exc:
                        logger.exception("❌ Transcription failed for %s: %s", f.filename, exc)
                        uploaded.append(
                            {
                                "filename": f.filename,
                                "storage_uri": storage_uri,
                                "ingest": "failed",
                                "error": f"Transcription error: {str(exc)}",
                            }
                        )
                else:
                    # PDFs: if scanned, enqueue OCR job instead of blocking ingestion.
                    if file_ext == ".pdf":
                        is_scanned, total_pages = _looks_scanned_pdf(Path(local_ingest_path))
                        if is_scanned:
                            doc.ocr_status = "queued"
                            doc.ocr_pages_total = int(total_pages) if total_pages else None
                            doc.ocr_pages_done = 0
                            doc.ocr_updated_at = datetime.utcnow()
                            enqueue_ocr_job(doc_id=int(doc.id), local_path=str(local_ingest_path))
                            uploaded.append(
                                {
                                    "filename": f.filename,
                                    "storage_uri": storage_uri,
                                    "ingest": "ocr_queued",
                                    "ocr": "queued",
                                    "pages_total": total_pages,
                                }
                            )
                        else:
                            background_tasks.add_task(ingest_single_file_safe, local_ingest_path)
                            uploaded.append(
                                {
                                    "filename": f.filename,
                                    "storage_uri": storage_uri,
                                    "ingest": "queued",
                                }
                            )
                    else:
                        background_tasks.add_task(ingest_single_file_safe, local_ingest_path)
                        uploaded.append({"filename": f.filename, "storage_uri": storage_uri, "ingest": "queued"})
            else:
                uploaded.append({"filename": f.filename, "storage_uri": storage_uri, "ingest": "skipped"})

        db.commit()
    finally:
        db.close()

    return {"uploaded": uploaded}


class DocAnswerRequest(BaseModel):
    question: str | None = None


@router.post("/{doc_id}/answer", response_model=QueryResponse)
async def answer_from_document(doc_id: int, request: DocAnswerRequest) -> QueryResponse:
    db = _get_db()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")

        filename = str(doc.filename)
        get_milvus_connection()
        if not utility.has_collection(config.COLLECTION_NAME):
            raise HTTPException(status_code=400, detail="Vector database collection not initialized")

        collection = Collection(config.COLLECTION_NAME)
        collection.load()

        safe_name = filename.replace('\\', "\\\\").replace('"', "\\\"")
        rows = collection.query(
            expr=f'source == "{safe_name}"',
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
            limit=int(getattr(config, "DOC_ANSWER_MAX_CHUNKS", 5000)),
        )

        transcript_texts = [
            str(r.get("text") or "")
            for r in (rows or [])
            if str(r.get("text") or "").strip()
        ]
        transcript = "\n\n".join(transcript_texts).strip()
        if not transcript:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No transcript/text chunks were found for this document in Milvus yet. "
                    "Please re-upload and wait for ingestion to complete."
                ),
            )

        user_question = str(request.question or "").strip()
        query = user_question if user_question else transcript

        query_service = _get_query_service()
        result = query_service.process_query(query)
        return QueryResponse(
            answer=str(result.get("answer", "")),
            sources=result.get("sources", []) or [],
            latency_ms=result.get("latency_ms"),
        )
    finally:
        db.close()


@router.get("/{doc_id}/milvus-chunks")
async def debug_milvus_chunks(doc_id: int) -> dict:
    db = _get_db()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")

        filename = str(doc.filename)
        get_milvus_connection()
        if not utility.has_collection(config.COLLECTION_NAME):
            return {
                "status": "no_collection",
                "collection": config.COLLECTION_NAME,
                "filename": filename,
                "count": 0,
                "samples": [],
            }

        collection = Collection(config.COLLECTION_NAME)
        collection.load()
        safe_name = filename.replace('\\', "\\\\").replace('"', "\\\"")

        limit = int(getattr(config, "DEBUG_CHUNK_SAMPLE_LIMIT", 20))
        rows = collection.query(
            expr=f'source == "{safe_name}"',
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
            limit=limit,
        )

        texts = [str(r.get("text") or "") for r in (rows or []) if str(r.get("text") or "").strip()]
        samples: list[str] = []
        for t in texts[:5]:
            samples.append(t[:200])

        def _safe_num(val: object) -> object:
            try:
                f = float(val)  # type: ignore[arg-type]
                return f if math.isfinite(f) else None
            except Exception:
                return None

        metadata_samples = []
        for r in (rows or [])[: min(5, len(rows or []))]:
            r2 = dict(r)
            r2["timestamp_start"] = _safe_num(r2.get("timestamp_start"))
            r2["timestamp_end"] = _safe_num(r2.get("timestamp_end"))
            r2["confidence"] = _safe_num(r2.get("confidence"))
            metadata_samples.append(r2)

        return {
            "status": "ok",
            "collection": config.COLLECTION_NAME,
            "filename": filename,
            "returned": len(texts),
            "limit": limit,
            "samples": samples,
            "metadata_samples": metadata_samples,
        }
    finally:
        db.close()


@router.get("/ingestion-status")
async def get_ingestion_status() -> dict:
    uploads_dir = Path(config.DATA_DIR) / "uploads" / "anonymous"
    error_log = uploads_dir / "ingestion_errors.log"

    if not error_log.exists():
        return {"status": "ok", "errors": []}

    try:
        lines = error_log.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []

    recent_errors = lines[-10:] if len(lines) > 10 else lines
    return {
        "status": "has_errors" if recent_errors else "ok",
        "errors": recent_errors,
    }


@router.post("/{doc_id}/summarize", response_model=QueryResponse)
async def summarize_document(doc_id: int) -> QueryResponse:
    """Summarize a specific document/audio by restricting retrieval to that file."""

    db = _get_db()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")

        filename = str(doc.filename)
        get_milvus_connection()
        if not utility.has_collection(config.COLLECTION_NAME):
            return QueryResponse(
                answer=(
                    "I couldn't find any indexed content for this file yet. "
                    "Please re-upload and wait for ingestion to complete."
                ),
                sources=[],
                latency_ms=0,
            )

        collection = Collection(config.COLLECTION_NAME)
        collection.load()

        safe_name = filename.replace('\\', "\\\\").replace('"', "\\\"")
        rows = collection.query(
            expr=f'source == "{safe_name}"',
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
            limit=int(getattr(config, "SUMMARY_MAX_CHUNKS", 2000)),
        )

        texts = [str(r.get("text") or "") for r in (rows or []) if str(r.get("text") or "").strip()]
        if not texts:
            return QueryResponse(
                answer=(
                    "I couldn't retrieve any stored text chunks for this file from the vector database. "
                    "Transcription may have succeeded, but ingestion may not have inserted chunks yet."
                ),
                sources=[],
                latency_ms=0,
            )

        raw_text = "\n\n".join(texts).strip()
        if len(raw_text) <= 600:
            answer = (
                f"This file contains the following content:\n\n{raw_text}"
                if raw_text
                else "I couldn't extract any readable content from this file."
            )
            return QueryResponse(
                answer=answer,
                sources=[
                    {
                        "filename": filename,
                        "content_type": str(doc.content_type or ""),
                        "relevance": 100.0,
                        "retrieval_relevance": 100.0,
                        "text": texts[0],
                    }
                ],
                latency_ms=0,
            )

        llm_context = raw_text

        client = OpenAI(
            api_key="ollama",
            base_url=config.OLLAMA_BASE_URL,
        )
        completion = client.chat.completions.create(
            model=config.OLLAMA_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarize files based only on provided content. "
                        "Never claim the file is empty if any content is shown."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Filename: {filename}\n\n"
                        "Summarize the following content (verbatim file chunks):\n\n"
                        f"{llm_context}\n\n"
                        "Write a short, direct summary."
                    ),
                },
            ],
            temperature=float(getattr(config, "LLM_TEMPERATURE", 0.1)),
            max_tokens=500,
        )
        answer = completion.choices[0].message.content or ""

        return QueryResponse(
            answer=str(answer),
            sources=[
                {
                    "filename": filename,
                    "content_type": str(doc.content_type or ""),
                    "relevance": 100.0,
                    "retrieval_relevance": 100.0,
                    "text": texts[0],
                }
            ],
            latency_ms=0,
        )
    finally:
        db.close()


@router.get("")
async def list_documents() -> dict:
    """List documents from Postgres."""

    db = _get_db()
    try:
        docs = db.query(Document).all()
        return {
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "storage_uri": d.storage_uri,
                    "content_type": d.content_type,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "ocr_status": getattr(d, "ocr_status", None),
                    "ocr_pages_total": getattr(d, "ocr_pages_total", None),
                    "ocr_pages_done": getattr(d, "ocr_pages_done", None),
                    "ocr_error": getattr(d, "ocr_error", None),
                    "ocr_updated_at": d.ocr_updated_at.isoformat() if getattr(d, "ocr_updated_at", None) else None,
                }
                for d in docs
            ]
        }
    finally:
        db.close()
