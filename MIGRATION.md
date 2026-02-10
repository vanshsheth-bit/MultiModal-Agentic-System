# Migration Guide: Legacy CLI to New Architecture

This document explains how the legacy CLI implementation maps to the new
modular backend and frontend.

## Legacy entrypoint

Old script:

- `ai-engineering-hub/multimodal-rag-assemblyai/main.py`

Behavior is preserved via:

- `backend/app/core/ingestion.py` (IngestionService)
- `backend/app/core/query.py` (QueryService)
- `backend/app/core/audio.py`
- `backend/app/core/milvus_client.py`
- `backend/app/cli.py` (new CLI that mirrors the old menu)

To run the CLI:

```bash
cd backend
python -m app.cli
```

## New FastAPI API

Main application:

- `backend/app/main.py`

Key endpoints:

- `GET /api/v1/health` – system health (Milvus, Postgres, Redis)
- `POST /api/v1/auth/login` – basic JWT login
- `POST /api/v1/query/text` – text question answering
- `POST /api/v1/query/audio` – audio question answering
- `POST /api/v1/docs/upload` – upload documents
- `GET /api/v1/docs` – list documents

## Frontend

Next.js 14+ app in `frontend/` with routes:

- `/dashboard` – stats + document list
- `/chat` – text and voice chat interface
- `/admin` – admin panel shell

The frontend communicates with the backend using:

- REST endpoints under `/api/v1`
- (Optionally) WebSockets for streaming in future extensions

## Data and Vector Store

Vector ingestion and querying remain based on Milvus:

- Same collection name and schema as the original implementation.
- Ingestion still reads from `DATA_DIR` and uses OpenAI embeddings.

## Backward compatibility notes

- The CLI workflow is preserved via `backend/app/cli.py`.
- The old `main.py` file remains untouched; new code lives under `backend/app/core`.
- All new services are configured via `.env` (see `.env.example`).
