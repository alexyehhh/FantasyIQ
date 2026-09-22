# FantasyIQ

AI-powered fantasy sports (NBA/NFL) analytics platform. See `docs/` for the
full Software Architecture Document.

## Milestone 1: Development environment

The current stack includes a health-checked backend, a Postgres schema, and a
frontend that confirms it can reach the backend. Milestone 3 adds one-game
ingestion through ESPN's public NBA/NFL site API endpoints, starting with
NFL; the NBA pipeline built alongside it works the same way.

### Prerequisites

- Docker + Docker Compose

### Running locally

```bash
cp .env.example .env
docker-compose up --build
```

- Backend: http://localhost:8000/api/v1/health
- Frontend: http://localhost:3000 (shows backend status)
- Postgres: localhost:5432
- Redis: localhost:6379 (not yet used by the app)

### Database migrations

With the stack running (`docker-compose up`), apply migrations from a second terminal:

```bash
docker-compose exec backend alembic upgrade head
```

Or, running the backend locally instead of in Docker (from `backend/`, with `.env` pointing at your Postgres):

```bash
alembic upgrade head
```

To create a new migration after changing a model:

```bash
alembic revision --autogenerate -m "describe the change"
```

Always review the generated migration file before applying it — autogenerate is a strong starting point, not a guarantee.

### NFL ingestion (Milestone 3)

No API key is required. With the stack running and migrations applied, first
find an ESPN event ID from the NFL scoreboard, then ingest one completed game:

```bash
docker-compose exec backend python -m data_pipeline.nfl_ingest --game-id <ESPN_EVENT_ID>
```

For example, the scoreboard endpoint is
`https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=YYYYMMDD`.

If ESPN returns `403` from inside Docker but works on the host, fetch on the
host and pipe the JSON into the backend container:

```bash
curl -s "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=ESPN_EVENT_ID" \
  | docker-compose exec -T backend python -m data_pipeline.nfl_ingest \
      --game-id ESPN_EVENT_ID --payload-stdin
```

The job fetches one ESPN game summary, validates and normalizes its nested
game/team/player-stat payload (merging each player's stats across ESPN's
passing/rushing/receiving/fumbles categories), and commits one transaction.
Re-running the same command updates the existing rows rather than creating
duplicates. If ESPN's summary endpoint returns `403`, the client falls back
to ESPN's documented CDN full-game package route. ESPN can change or block
undocumented endpoints, so provider access stays isolated and the client
applies a timeout.

NFL stats live in their own `player_game_stats_nfl` table (passing/rushing/
receiving-shaped), separate from the NBA-shaped `player_game_stats` table —
teams, players, and games are shared across both sports.

### NBA ingestion

The NBA pipeline works the same way, just with basketball's endpoints and
stat shape:

```bash
docker-compose exec backend python -m data_pipeline.nba_ingest --game-id <ESPN_EVENT_ID>
```

The scoreboard endpoint is
`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD`,
and the same `--payload-stdin` fallback and idempotent-upsert behavior apply.

### Seed data (manual sanity check only — not real ingestion)

```bash
cd backend
python scripts/seed.py
```

Inserts two fake NBA teams, two players, one game, and two stat lines, so you can confirm the schema works end-to-end without calling the external provider.

### Backend tests

```bash
cd backend
pip install -e ".[dev]"
pytest
```

Note: `tests/test_models.py` hits a real Postgres database (not sqlite/mocked) — make sure Postgres is running and migrations are applied first.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Project layout

- `backend/` — FastAPI app and `data_pipeline/` ingestion jobs (modular monolith;
  business logic in `app/services`, AI agent + tools in `app/ai`, ML inference in `app/ml`)
- `frontend/` — Next.js app
- `ml/` — offline model training and backtesting (separate from backend inference code)
- `data_pipeline/` — ingestion jobs
- `docs/` — architecture docs
