# Multimodal Agentic RAG System

This repository contains a multimodal RAG system with:

- A Python backend (FastAPI + Milvus + Postgres + Redis + MinIO)
- A Next.js 14+ frontend (dashboard, chat, admin)
- Docker Compose for local development

## Prerequisites

- Docker and Docker Compose
- Python 3.11 (for local backend work)
- Node.js 20+ (for local frontend work)

## Configuration

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

At minimum you must set:

- `ASSEMBLYAI_API_KEY`
- `OPENAI_API_KEY`

## Running with Docker Compose

From the repository root:

```bash
docker-compose -f infra/docker-compose.yml up --build
```

Services:

- Backend API: http://localhost:8000
- API docs: http://localhost:8000/api/docs
- Frontend: http://localhost:3000
- Postgres: localhost:5432
- Redis: localhost:6379
- MinIO: http://localhost:9000 (console: http://localhost:9001)

## Running backend locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Legacy CLI (backward compatible):

```bash
python -m app.cli
```

## Running frontend locally

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

## Tests

```bash
cd backend
pytest
```

## Migration verification

A simple script to verify that the stack starts correctly:

```bash
bash scripts/verify-migration.sh
```
