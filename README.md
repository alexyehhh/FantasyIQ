# FantasyIQ

AI-powered fantasy sports (NBA/NFL) analytics platform. See `docs/` for the
full Software Architecture Document.

## What it does

- Ingests NBA and NFL game stats from ESPN's public site API into Postgres,
  idempotently (safe to re-run).
- Exposes a REST API for players and their per-game stat lines.
- A Next.js frontend to search players and view a chart of their recent-game
  stats.

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

### NFL ingestion

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

### Player API

With data ingested (or seeded — see below), the backend exposes read
endpoints for players and their game stats:

```
GET /api/v1/players?sport=NBA&team_id=1&search=curry&limit=50&offset=0
GET /api/v1/players/{id}
GET /api/v1/players/{id}/stats?limit=10
```

`sport` (if given) must be `NBA` or `NFL`. `search` matches player name
(case-insensitive substring). The stats endpoint returns each game's stat
line most-recent-first; the shape of `stats` depends on the player's sport
(NBA: points/rebounds/assists/...; NFL: passing/rushing/receiving/...),
since the two sports are stored in separate tables (see §9 of the
architecture doc). Business logic lives in `app/services/players.py`,
called by both this API and, later, the AI tool layer.

### Frontend player page

With the backend running and data ingested or seeded, `/players` is a search
page (by name and/or sport) linking to `/players/{id}`, a detail page showing
the player's info and a chart (Recharts) of one stat across their recent
games, with a dropdown to switch which stat is charted. All backend calls go
through `frontend/src/lib/api.ts`.

Server-rendered pages (the player detail page) run inside the frontend's own
Docker container, where `localhost` points at that container rather than the
backend one — `INTERNAL_API_URL` (set in `docker-compose.yml` to the
backend's Compose service name) is used there instead of
`NEXT_PUBLIC_API_URL`, which browser-side code keeps using since it isn't
reachable from the browser.

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

To run frontend tests (Jest + React Testing Library):

```bash
cd frontend
npm test
```

## Project layout

- `backend/` — FastAPI app and `data_pipeline/` ingestion jobs (modular monolith;
  business logic in `app/services`, AI agent + tools in `app/ai`, ML inference in `app/ml`)
- `frontend/` — Next.js app
- `ml/` — offline model training and backtesting (separate from backend inference code)
- `data_pipeline/` — ingestion jobs
- `docs/` — architecture docs
