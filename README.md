# Multimodal Agentic RAG System

This repository contains a **multimodal, production-style RAG system** with:

- A Python backend (FastAPI + Milvus + PostgreSQL + Redis + Elasticsearch + MinIO)
- A Next.js 14+ frontend (dashboard, chat, history, admin)
- Optional agentic reasoning via CrewAI and an Ollama-backed LLM
- Docker-based infrastructure for local development

The system is designed to be **production-ready** with telemetry (Sentry, Prometheus),
token/cost tracking, caching, and confidence-based guardrails against hallucinations.

## Backend overview (`backend/`)

Backend technologies:

- **FastAPI** application (`app/main.py`) with:
  - API router (`/api/v1`) for auth, document management, and query endpoints
  - WebSocket support for chat (when available)
  - CORS, structured logging middleware, and global error handling
  - Optional Sentry + Prometheus instrumentation
- **Vector database**: Milvus (`pymilvus`) storing multimodal chunks (PDF, audio, text)
- **Hybrid retrieval**: Milvus + Elasticsearch BM25 with optional CrossEncoder reranker
- **RAG / query orchestration**: `app/core/query.py`
  - Audio + text queries
  - Hybrid search, reranking, retrieval-confidence based controller
  - Strict grounding to prevent hallucinations
  - Optional CrewAI-based multi-agent reasoning with Ollama fallback
- **Ingestion pipeline**: `app/core/ingestion.py`
  - PDF, audio (AssemblyAI), and text ingestion
  - Sentence-aware, overlapping chunking
  - Parallel ingestion with configurable concurrency
  - Bulk indexing into Milvus and Elasticsearch
- **Persistence & analytics**:
  - PostgreSQL via SQLAlchemy models (`app/models/database.py`)
  - `QueryLog` with latency, retrieval quality, token counts, and cost estimates
  - `AnalyticsSnapshot` for daily aggregates
- **Caching & infra helpers**:
  - Redis-based caching for embeddings/retrieval/LLM (`app/core/cache.py`)
  - Milvus and Elasticsearch helpers (`app/core/milvus_client.py`, `app/core/elasticsearch_client.py`)

Backend dependencies are defined in `backend/requirements.txt`.

## Frontend overview (`frontend/`)

Frontend technologies:

- **Next.js 14+** (App Router) with React 18
- **UI stack**:
  - Tailwind CSS (`tailwind.config.ts`, `global.css`)
  - `lucide-react` icons
  - `framer-motion` for animations
- **Data & state**:
  - `@tanstack/react-query` for API fetching and caching
  - `axios` for HTTP requests to the backend API
- **Key features/pages** (in `frontend/app/` and `frontend/components/`):
  - Chat interface for querying the RAG backend
  - Document management and upload flows
  - History/analytics dashboards powered by backend telemetry
- Sentry config files (`sentry.*.config.ts`) are present for optional frontend error tracking.

## Prerequisites

- Docker and Docker Compose (for full stack via `infra/`)
- Python 3.11 (for local backend work)
- Node.js 20+ (for local frontend work)

You also need running instances of:

- PostgreSQL (default: `postgresql://postgres:postgres@localhost:5432/postgres`)
- Redis (default: `redis://localhost:6379/0`)
- Milvus (vector database)
- Elasticsearch (for BM25 search)
- MinIO or compatible S3 storage for document blobs

The `infra/` folder (if present) contains Docker Compose definitions to run this stack locally.

## Configuration

Configuration is environment-driven via `.env` (root) and service-specific env files.

From the repository root, copy the example env file:

```bash
cp .env.example .env
```

At minimum you must set:

- `ASSEMBLYAI_API_KEY` – for audio transcription
- `OPENAI_API_KEY` – used by the OpenAI-compatible client (Ollama base URL is configured separately)

Backend configuration is defined in `backend/app/core/config.py` using Pydantic `BaseSettings`.

## Running with Docker Compose

From the repository root, assuming you have `infra/docker-compose.yml`:

```bash
docker-compose -f infra/docker-compose.yml up --build
```

Services (defaults):

- Backend API: http://localhost:8000
- API docs (OpenAPI): http://localhost:8000/api/docs
- Frontend: http://localhost:3000
- Postgres: `localhost:5432`
- Redis: `localhost:6379`
- MinIO: http://localhost:9000 (console: http://localhost:9001)
- Milvus, Elasticsearch, and other infra as defined in `infra/docker-compose.yml`

## Running backend locally (without Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt

# Ensure Postgres, Redis, Milvus, Elasticsearch, and MinIO are running

uvicorn app.main:app --reload
```

Backend will be available at:

- API root health check: http://localhost:8000/
- API docs: http://localhost:8000/api/docs

Legacy CLI (for ingestion and local testing):

```bash
cd backend
python -m app.cli
```

This CLI allows you to run the ingestion pipeline and query the system from the terminal.

## Running frontend locally (without Docker)

```bash
cd frontend
npm install
npm run dev
```

Then open:

- Frontend: http://localhost:3000

Make sure the backend is running at the URL expected by the frontend (often `http://localhost:8000`).

## Tests

Run backend tests:

```bash
cd backend
pytest
```

You can also add frontend tests or linting via:

```bash
cd frontend
npm run lint
```

## Migration verification

A simple script to verify that the stack starts correctly (where available):

```bash
bash scripts/verify-migration.sh
```

This script is intended to validate that the core services (backend + infra) come up and basic
health checks pass after migrating or refactoring the system.
