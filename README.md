# FantasyIQ

AI-powered fantasy sports (NBA/NFL) analytics platform. See `docs/` for the
full Software Architecture Document.

## What it does

- Ingests NBA and NFL game stats from ESPN's public site API into Postgres,
  idempotently (safe to re-run).
- Keeps a directory of every NBA and NFL team and player (photos, team,
  number, position, bio), the current injury report, and the regular-season
  schedule, synced from ESPN.
- Exposes a REST API for players, their per-game stat lines (with opponent and
  result), injuries, and each player's next game.
- A Next.js frontend to search players and open a player page: header with the
  next game, trend chart, averages, consistency, and a full game log.

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

ESPN's edge answers browser-style (or any made-up) `User-Agent` headers with
`403 Access Denied` while serving the default `httpx` one, so the client
deliberately sends no custom `User-Agent`. If ESPN still returns `403` from
inside Docker but works on the host, fetch on the host and pipe the JSON into
the backend container:

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

### Player directory sync

Game ingestion loads box scores; this job keeps the reference data current —
every team's logo and colors, every rostered player's team, number, position,
headshot and bio, the current injury report, and the regular-season schedule
(with final scores for games already played). It is idempotent, so run it
whenever you want fresh rosters and injuries (daily is plenty):

```bash
docker-compose exec backend python -m data_pipeline.espn_directory --sport all
```

`--sport` takes `NBA`, `NFL`, or `all` (default). It takes about 20 seconds for
both leagues. If one team's roster or schedule fails to load it is reported and
skipped, and nobody is marked inactive on that run, since a missing roster would
otherwise look like a whole team leaving the league.

Rosters own a player's *current* team, position and active flag; game ingestion
only sets those for players it creates, so ingesting an old game never moves a
traded player back to his former team. Run the directory sync before ingesting
games so those players already exist.

ESPN only reports NBA positions as G/F/C, not PG/SG/SF/PF; NFL positions are
specific. A game log's opponent and result are worked out from the player's
*current* team, so games played for a former team show no opponent.

### Player API

With data ingested (or seeded — see below), the backend exposes read
endpoints for players and their game stats:

```
GET /api/v1/players?sport=NFL&position=RB&position=WR&search=smith&sort=fantasy_points&limit=50&offset=0
GET /api/v1/players/{id}
GET /api/v1/players/{id}/stats?limit=10
GET /api/v1/players/{id}/schedule
```

Each player includes `team` (name, abbreviation, logo, color), `headshot_url`
and `injury_status`; the detail response adds height, weight, birth date,
college, experience, the full `injury` report, and `next_game` (opponent, home
or away, start time). Each stat line includes `opponent`, `is_home`, both
scores, `week` (NFL) and `result` (`W`/`L`/`T`). `/schedule` returns the player's
team's games for the current season, played and upcoming, in date order (NFL stops
at week 17); a team's `bye_week` is on its `team` object. Timestamps are ISO 8601
in UTC.

`sport` (if given) must be `NBA` or `NFL`. `position` may be repeated to match any
of several position codes (ESPN's, so kickers are `PK`). `search` matches player
name (case-insensitive substring). `sort` is `name` (default) or `fantasy_points`,
which ranks most first by each player's fantasy points over the latest season with
stats (default scoring, `app/services/scoring.py`), players with none last, and
needs `sport` since points aren't comparable across sports. Listed players carry
that total as `fantasy_points`. The stats endpoint returns each game's stat
line most-recent-first; the shape of `stats` depends on the player's sport
(NBA: points/rebounds/assists/...; NFL: passing/rushing/receiving/...),
since the two sports are stored in separate tables (see §9 of the
architecture doc). Business logic lives in `app/services/players.py`,
called by both this API and, later, the AI tool layer.

### Frontend player pages

With the backend running and the directory synced, `/players` is a search page
that opens on NFL (NFL/NBA toggle) with position buttons: QB, RB, WR, TE, W/R/T
(any RB, WR or TE), K and DEF (shown but disabled: team defenses aren't tracked
yet) for the NFL, and G, F, C and Util (everyone) for the NBA. ESPN reports NBA
positions only as G/F/C, so PG/SG/SF/PF eligibility has to wait for Yahoo. Players
are ranked by fantasy points, most first, 50 to a page with Previous 50 / Next 50
buttons that scroll back to the top of the page; a search or position change
also restarts at the top of the ranking. Rows have photos, teams,
fantasy points and injury status and link to `/players/{id}`. A player page shows:

- a header with the photo, team, position, number, the team's bye week (NFL),
  health status and the team's next game, plus last-10 averages (fantasy points
  first) with a last-5-vs-all trend;
- the player's injury note, when there is one;
- a bar chart (Recharts) of one stat over the last 5, 10 or all games with an
  average line, switchable between the position's key stats and fantasy points;
- an averages table and a consistency plot (floor / median / average / ceiling);
- a game log for the current season, from its first game: results with the
  player's stats, then upcoming games with kickoff times. Earlier seasons aren't
  listed (they still count in the chart and averages). A football season is shown
  whole, bye week included (through week 17). A basketball season is far longer,
  so the log shows one page of 20 games at a time, counted from game 1, with
  Previous and Next buttons that replace the page. It opens on the first page that
  still has games to come, so it moves on to games 21–40 once the first 20 are
  played.

Kickers and punters show their schedule but no stats yet. Field goals and extra
points (made and attempted) are stored per game, and NFL ingestion also stores every
field goal attempt with its distance and result (`field_goal_kicks`, one row per
play), read from the game's play-by-play because distance isn't in the box score.
The page and the default scoring don't use them yet, so there are no fantasy points
for kickers until they do. Ingestion rejects a game whose kicks don't add up to each
kicker's box-score FG line. Games ingested before the stat tables were widened read 0
for the new columns (NBA makes and free throws, NFL kicking and return touchdowns) and
have no kick rows until they are re-ingested; re-running `nba_ingest`/`nfl_ingest` for
a game is safe.

Fantasy points use FantasyIQ's default scoring, which only needs stats already
stored. The weights live in both `backend/app/services/scoring.py` (for the
ranking) and `frontend/src/lib/scoring.ts` (for individual games); tests on both
sides pin the same worked examples so they can't drift. Game dates and times are shown in US
Pacific time. All backend calls go through `frontend/src/lib/api.ts`.

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

Note: the database tests hit a real Postgres (not sqlite/mocked) and assume it
is empty, so **don't run them against a database holding synced or ingested
data**. Use a separate one:

```bash
docker-compose exec postgres createdb -U fantasyiq fantasyiq_test
cd backend
POSTGRES_DB=fantasyiq_test alembic upgrade head
POSTGRES_DB=fantasyiq_test pytest
```

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
