# FantasyIQ

AI-powered fantasy sports (NBA/NFL) analytics platform. See `docs/` for the
full Software Architecture Document.

## Milestone 1: Development environment

At this stage the stack is just a health-checked backend and a frontend
that confirms it can reach it. No database schema, no business logic yet.

### Prerequisites

- Docker + Docker Compose

### Running locally

```bash
cp .env.example .env
docker-compose up --build
```

- Backend: http://localhost:8000/api/v1/health
- Frontend: http://localhost:3000 (shows backend status)
- Postgres: localhost:5432 (not yet used by the app)
- Redis: localhost:6379 (not yet used by the app)

### Backend tests

```bash
cd backend
pip install -e ".[dev]"
pytest
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Project layout

- `backend/` — FastAPI app (modular monolith; business logic in `app/services`,
  AI agent + tools in `app/ai`, ML inference in `app/ml`)
- `frontend/` — Next.js app
- `ml/` — offline model training and backtesting (separate from backend inference code)
- `data_pipeline/` — ingestion jobs
- `docs/` — architecture docs
