# FantasyIQ

A fantasy football and basketball analytics app. Browse NFL and NBA player and
team-defense stats, compare players for start/sit decisions, and get an
AI-generated explanation of who to start.

## Features

### Player and defense search

`/players` lets you search NFL and NBA players by name, filter by position
(QB, RB, WR, TE, W/R/T, K, DEF for the NFL; G, F, C, Util for the NBA), and
browse them ranked by fantasy points. Each row shows a photo, team, fantasy
points and injury status, and links to a full player page. NFL team defenses
are listed alongside players under the DEF filter and link to `/defenses/{id}`.

### Player and defense pages

A player's page (`/players/{id}`) shows:

- A header with photo, team, position, number, bye week, injury status, next
  game, and season totals for their key stats, each with a rank among players
  at the same position.
- A bar chart of any key stat (or fantasy points) over the last 5, 10, or all
  games.
- An averages table and a floor/median/average/ceiling consistency view.
- A full game log for the season, including games in progress and upcoming
  games.

Team defenses have the same layout at `/defenses/{id}`, with sacks,
takeaways, and points/yards allowed in place of offensive stats.

### Who should I start?

`/start` is a start/sit comparison tool. Search for players or team defenses
(or pick from the ranked Top Players list) to add up to five to the
comparison, then press **View advice** for a recommendation, a
floor-to-ceiling comparison chart, and a card per player explaining the call
(injury status, projection gap, boom-or-bust risk). A player whose game has
already started or finished is shown as unavailable to start.

You can change the scoring format (FantasyIQ PPR, Half-PPR, Standard, or a
custom set of weights), step through NFL weeks, and star players to save them
to "My team" for quick access later. The current comparison is saved in the
page's URL, so you can share or bookmark it.

### AI Analyst

An API endpoint explains a start/sit decision in plain language, citing the
same stats and projections shown elsewhere in the app:

```
POST /api/v1/analyst/start-sit
{"candidates": [{"kind": "player", "entity_id": 1384}, {"kind": "defense", "entity_id": 67}],
 "week": 3, "scoring": "default"}
```

This requires a Gemini API key — see "Running locally" below.

### API

The backend also exposes a plain REST API for players, defenses, their stats,
schedules, and projections, if you want to query the data directly. See
`docs/` for the full endpoint reference.

## Running locally

### Prerequisites

- Docker + Docker Compose

### Start the stack

```bash
cp .env.example .env
docker-compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000/api/v1/health

To use the AI Analyst, add a free Gemini API key to `.env` before starting:

```
GEMINI_API_KEY=your-key-here
```

Get one at https://aistudio.google.com/apikey. Without it, the analyst
endpoint returns a `503` rather than failing partway through.

### Apply database migrations

With the stack running, from a second terminal:

```bash
docker-compose exec backend alembic upgrade head
```

### Running tests

Backend:

```bash
cd backend
pip install -e ".[dev]"
pytest
```

Frontend:

```bash
cd frontend
npm install
npm test
```

## Project layout

- `backend/` — FastAPI app and data ingestion jobs
- `frontend/` — Next.js app
- `ml/` — offline model training and backtesting
- `docs/` — architecture docs
