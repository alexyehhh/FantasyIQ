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
- Worker: no port; it keeps games, injuries, rosters and the schedule current (see "Keeping the data current")

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
(with final scores for games already played). The worker runs it every 6 hours
(see "Keeping the data current"); it is idempotent, so you can also run it by hand
whenever you want fresh rosters and injuries right now:

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

### Bulk game ingestion

The directory sync records every game and marks it final once it's played; this job
loads the box score for each finished game that doesn't have one yet, so you don't
have to look up ESPN event IDs. The worker does this automatically, so by hand it is
only needed for `--reingest` or a big backlog:

```bash
docker-compose exec backend python -m data_pipeline.backfill --sport all
```

`--sport` takes `NBA`, `NFL` or `all` (default). `--reingest` reloads games that already
have stats too, which is how a newly added stat column gets filled in for old games.
`--limit N` caps the games per sport and `--delay` sets the pause between ESPN requests
(default 0.5 seconds). A game that fails (ESPN error, or a payload that doesn't reconcile
with its box score) is listed and skipped, the rest still run, and the exit code is 1 if
anything failed. Every ingest upserts, so re-running is always safe.

### Keeping the data current (the worker)

Everything above can be run by hand, but you don't have to: `docker-compose up` also starts a
`worker` service (`python -m data_pipeline.worker`) that keeps the data fresh on its own. It is
the only thing that calls ESPN. The API only reads the database (apart from the Sleeper projections
source, see "Projections"), so the number of people using the
app changes neither how hard ESPN is hit nor how fast a page loads. Reloading a page shows what the
worker has stored, at most a few seconds behind.

| job | runs | does |
| --- | --- | --- |
| `live` | every 15 s | pulls stats for games in progress, games that should have started, and finished games with no final box score; each game at most every 30 s |
| `injuries` | every 15 min | the injury report (2 requests) |
| `directory` | every 6 h | teams, rosters, schedule and injuries (about 130 requests, 35 s) |
| `backfill` | every hour | box scores of finished games too old for the live job (up to 20 per sport per run) |

A game counts for the live job when it is in progress; past its start time but still `scheduled`
(within 48 hours); or `final` without a box score taken after it ended (`games.stats_final`,
within 14 days). Intervals are settings: `WORKER_LIVE_INTERVAL_SECONDS`,
`WORKER_INJURIES_INTERVAL_SECONDS`, `WORKER_DIRECTORY_INTERVAL_SECONDS`,
`WORKER_BACKFILL_INTERVAL_SECONDS`, plus `LIVE_REFRESH_COOLDOWN_SECONDS` (30) and
`LIVE_REFRESH_TIMEOUT_SECONDS` (8). The code is `data_pipeline/worker.py` and
`data_pipeline/refresh.py`. In development it restarts itself when backend code changes.

**Rate limits.** ESPN publishes none for this API, so the client is deliberately gentle. Every
request goes through one gate that spaces them at least 0.25 s apart (`ESPN_MIN_REQUEST_INTERVAL_SECONDS`),
so never more than 4 a second. If ESPN answers 429 or 503 the worker stops asking altogether
(honouring `Retry-After`, else 60 s, doubling each time to 15 minutes) and carries on afterwards. In
practice a quiet hour is about 30 requests, and a busy NFL Sunday about one request per live game
every 30 s.

**Staying up.** A job that fails is logged, recorded in the `job_runs` table and retried after 1, 2,
4 ... up to 15 minutes; it can't stop the worker or the other jobs, and one bad game never costs the
others. Last-run times are stored in the database, so a restart or a crash loop doesn't rerun
everything and hit ESPN again. `GET /api/v1/health/jobs` shows when each job last succeeded, its
failures and last error, and `status: "degraded"` when one is overdue. You can run several workers
(for redundancy): they elect one leader with a Postgres advisory lock, the rest wait, and one takes
over within about 15 seconds if the leader dies.

While a game is on, its kicks and team-defense lines are only stored when they reconcile with the
box score (a finished game that doesn't is still rejected, as above); the player lines always are.

### Player API

With data ingested (or seeded — see below), the backend exposes read
endpoints for players and their game stats:

```
GET /api/v1/players?sport=NFL&position=RB&position=WR&search=smith&sort=fantasy_points&limit=50&offset=0
GET /api/v1/players/{id}
GET /api/v1/players/{id}/stats?limit=10
GET /api/v1/players/{id}/schedule
GET /api/v1/players/{id}/season
GET /api/v1/defenses?search=bears&sort=fantasy_points&limit=50&offset=0
GET /api/v1/defenses/{team_id}
GET /api/v1/defenses/{team_id}/stats?limit=10
GET /api/v1/defenses/{team_id}/schedule
GET /api/v1/defenses/{team_id}/season
```

Each player includes `team` (name, abbreviation, logo, color), `headshot_url`
and `injury_status`; the detail response adds height, weight, birth date,
college, experience, the full `injury` report, and `next_game` (opponent, home
or away, start time). Each stat line includes `opponent`, `is_home`, both
scores, `status` (`scheduled`, `in_progress` or `final`), `week` (NFL) and `result` (`W`/`L`/`T`,
only once the game is `final`; a game in progress has its running score and no result). A line
from a game in progress is its stats so far. `/schedule` returns the player's
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

### Scoring in the API

Every endpoint that scores (the players list and `/players/{id}/stats`, and all the
defense endpoints that return points) takes a `scoring` query parameter: `default` (or
omitted) for the FantasyIQ scoring of the sport, or an inline JSON `ScoringConfig`, for
example

```
GET /api/v1/players/123/stats?scoring={"name":"Flat kicker","sport":"NFL","player_weights":{"field_goals_made":3}}
```

`GET /api/v1/scoring/presets/{sport}` returns the default config itself (weights and
brackets), which is what the frontend describes under a game log.

An invalid config, an unknown preset, or a config for the other sport is a `422` that says
why. Choosing a `scoring` on the players list needs a `sport`. The JSON travels in the URL,
so it suits a config of a few hundred bytes; saved per-league configs will replace that once
leagues can be linked.

Each entry of `/players/{id}/stats` carries `fantasy_points` for that game under the chosen
scoring, and an NFL kicker's entries carry `kicks` (`distance` and `result`: `made`,
`missed` or `blocked`). A team defense (D/ST) is an NFL team, addressed by team id:
`/defenses` lists and ranks them, `/defenses/{team_id}` gives the team with its bye week and
next game, `/stats` the game log (sacks, interceptions, points allowed, ... plus
`fantasy_points`), and `/schedule` the season. The other endpoints work the same way as
the player ones.

### Projections

`GET /api/v1/projections` answers "who should I start?": it projects players and/or team
defenses for their next game and ranks them by fantasy points under the caller's scoring.

```
GET /api/v1/projections?sport=NFL&player_id=1384&player_id=1370&defense_id=67&source=sleeper&week=3
GET /api/v1/projections/top?sport=NFL&slot=FLEX&source=sleeper&week=3&limit=30
GET /api/v1/players/{id}/projection?source=sleeper
GET /api/v1/defenses/{team_id}/projection
GET /api/v1/projections/sources
```

A **source** decides the expected *stat line* (yards, receptions, field goals by distance,
sacks, points allowed); the backend then scores that line with the request's `scoring`
(same parameter as everywhere else), once, for every source. So each source follows the
league's own settings, and a stat the league scores but the source doesn't project
(`unprojected_stats`, e.g. 4th-down stops from Sleeper) counts as zero. Ones that almost never
happen (kick return touchdowns) count as zero without being listed. Sources are classes in
`app/services/projections/` registered in `PROVIDERS`; a new one (later, our own model) needs
only a `project` method.

- `sleeper`: Sleeper's public projections (produced by Rotowire), which know the opponent.
  Fetched on demand by the API server and kept in memory for 15 minutes
  (`SLEEPER_CACHE_TTL_SECONDS`); nothing from Sleeper is stored. The endpoint is undocumented,
  so a change there is a `502`, not wrong numbers: rows are matched to our players by name and
  team, and must agree with our schedule on the opponent, or the player is `unavailable`.
  Sleeper leaves out players it doesn't expect to play and fringe players.

`sleeper` is the only source, and the default. A player's own recent games are deliberately not
a source: one good game says little about what they will score next week (they were removed
after being tried), and they never move a projection. They only size its range, below.

**Spread and odds.** Every entry has `std`, `low` and `high` (one standard deviation either
side of the projection). It comes from the player's own game-to-game swings in their last games
(`app/services/projections/history.py`), blended with a typical spread for their position (a share of the projection: QB 35%,
RB 50%, WR/TE 55%, K 35%, D/ST 60%, NBA 30%; assumptions, not fitted) in proportion to the
games behind it: with n games history counts n/(n+4), so it stands alone only once there are
many. `spread_basis` says which applied and `games_sampled` how many games it rests on. When several are compared, `chance_best` is each
one's chance of scoring the most, from 4,000 seeded draws of normally distributed scores
around the projections, treating players as independent.

`/projections/top` ranks a lineup slot (NFL `QB RB WR TE FLEX SUPERFLEX K DST`, NBA
`G F C UTIL`) by projection, a page at a time (`limit`, default 30, and `offset`; the response's
`total` is how many there are). The ranking covers everyone the source projects for the week
(NFL) or the next day of games (NBA) and that we have as an active player, scored under the
request's `scoring` and leaving out anyone listed Out, on injured reserve or Doubtful (a
Doubtful player named in a comparison is still projected, with a warning); only the page
returned is projected in full (game, range, flags). So a player with no games yet is ranked as
long as the source projects them, and a team on a bye simply isn't there. Responses carry
`week`: the NFL week in play (that of the earliest unfinished game, so it rolls over after
Monday night), or the requested one.

Each entry has a `status`: `ok`, `out` (injury status Out or Injured Reserve: 0 points),
`no_game` (bye week, or nothing scheduled) or `unavailable` (the source has nothing; `notes`
says why). Without `week`, each is projected for its team's next game; `week` (NFL) picks that
week's game, so a bye shows as `no_game`. Questionable and Doubtful players are projected as
if they play, with a note. Points-allowed brackets are scored over a spread of outcomes around
the projected points allowed (assumed spread `POINTS_ALLOWED_SD` = 9.5 points), not by looking
up the average, and a kicker's Sleeper distance ranges are treated as evenly spread
(`approximate` is set if a bracket boundary falls inside one).

### Who should I start? (frontend)

`/start` (nav: Start / Sit) is a FantasyPros-style start/sit page. Search for players (or team
defenses) or click rows in the Top players list to fill up to five slots, then press View
advice for a verdict ("Start Jahmyr Gibbs", with a Clear edge / Lean / Toss-up label from the
odds that the last starter outscores the first sitter), a floor-to-ceiling plot on one axis, and
a card per player with the reasons (injury, points ahead or behind, boom-or-bust, stats the
source doesn't project). A player whose game has started or finished stays in Top players
(marked Final or Live) and can be compared, but is highlighted "Game over: can't be started", is
never recommended and takes no part in the verdict or the odds. "Starting
spots" marks the top N as starters when you're choosing more than one. Top players is ranked
per lineup slot (QB, RB, WR, TE, FLEX, Superflex, K, DST; the NBA has G, F, C, Util), 30 to a
page with Previous and Next buttons. The week
stepper (NFL) moves the whole page to another week. The scoring dropdown offers FantasyIQ
(PPR), Half-PPR, Standard and Custom. The weights under the gear follow the choice (Half-PPR
shows 0.5 per reception), and editing one, or picking Custom, continues from there; kicker and
defense scoring always stay as in the default. The source is shown as a label (Sleeper) until
there is more than one to choose from. My team is a starred list, kept in this browser
(localStorage) until leagues can be linked. The comparison lives in the address (`?slot=WR&week=5&scoring=half&picks=p1384,d67&advice=1`,
defaults left out), so a refresh or a shared link shows the same thing, and opening `/start` with
no address returns to the last one from this browser. All the numbers come from the projections API
above; the page only ranks and explains them (`src/lib/startSit.ts`).

### Frontend player pages

With the backend running and the directory synced, `/players` is a search page
that opens on NFL (NFL/NBA toggle) with position buttons: QB, RB, WR, TE, W/R/T
(any RB, WR or TE), K and DEF (team defenses, ranked the same way and linking to
`/defenses/{team_id}`) for the NFL, and G, F, C and Util (everyone) for the NBA. ESPN reports NBA
positions only as G/F/C, so PG/SG/SF/PF eligibility has to wait for Yahoo. Players
are ranked by fantasy points, most first, 50 to a page with Previous 50 / Next 50
buttons that scroll back to the top of the page; a search or position change
also restarts at the top of the ranking. Rows have photos, teams,
fantasy points and injury status and link to `/players/{id}`. A player page shows:

- a header with the photo, team, position, number, the team's bye week (NFL),
  health status and the team's next game, plus the season's totals for the
  position's key stats (fantasy points first), each with its rank among players
  at the same position ("#3 of 43 QB", "T-#5" when tied, and a green rank for the
  top five). Last-10 averages and the last-5-vs-all trend stay in the averages
  table and chart; before a player's first game of the season (the NBA offseason) the
  tiles show dashes rather than last-10 averages;
- the player's injury note, when there is one;
- a bar chart (Recharts) of one stat over the last 5, 10 or all games with an
  average line, switchable between the position's key stats and fantasy points;
- an averages table and a consistency plot (floor / median / average / ceiling). The chart,
  averages and consistency plot use finished games only, since a game in progress would drag
  them down; the header's season totals and ranks do include it, as its running total;
- a game log for the current season, from its first game: results with the
  player's stats, a game in progress marked Live with its running score and the stats so far,
  then upcoming games with kickoff times. A football season is shown
  whole, bye week included (through week 17). A basketball season is far longer,
  so the log shows one page of 20 games at a time, counted from game 1, with
  Previous and Next buttons that replace the page. It opens on the first page that
  still has games to come, so it moves on to games 21–40 once the first 20 are
  played.

A kicker's page shows field goals and extra points (made and attempted), fantasy points,
and each game's kicks in the log as distances ("24, 52, 43 (miss)"). NFL ingestion stores
every field goal attempt with its distance and result (`field_goal_kicks`, one row per
play), read from the game's play-by-play because distance isn't in the box score, and
rejects a game whose kicks don't add up to each kicker's box-score FG line. Punters show
only their schedule (no punting stats are stored), and the players list shows a dash for
their points. Games ingested before the stat tables were widened read 0 for the new
columns (NBA makes and free throws, NFL kicking and return touchdowns) and have no kick
rows until they are re-ingested (`python -m data_pipeline.backfill --reingest`).

NFL ingestion also stores each team's defense/special teams line per game
(`team_game_stats_nfl`): sacks, interceptions, fumble recoveries, safeties, blocked
kicks, defensive touchdowns, kick/punt return touchdowns, 4th-down stops, yards allowed
and points allowed. They come from the opponent's box-score totals and the drive
results, defined as Yahoo scores a D/ST: points allowed leave out interception and
fumble return touchdowns (with their extra points) and safeties, while kick and punt
return touchdowns still count against the team. Ingestion cross-checks the drives
against the box score's defensive touchdown and safety counts, and rejects a game it
can't explain rather than store a wrong points-allowed figure. Not stored yet, for lack
of a real sample to verify against: extra points returned by the defense, blocked extra
points, and three-and-outs. Like the kicks, these rows exist only for games ingested
since the table was added.

Fantasy points come from the backend, under FantasyIQ's default scoring: each game in
a player's or defense's stats carries `fantasy_points`, and the game log's "FPTS uses ..."
note is written from the config served by `GET /api/v1/scoring/presets/{sport}`, so the
weights exist in one place only. A team defense has its own page at `/defenses/{team_id}`
with the same layout as a player's (header with the bye week and next game, chart,
averages, consistency, game log), with sacks, takeaways, scores and points and yards
allowed as its stats. Game dates and times are shown in US Pacific time. All backend
calls go through `frontend/src/lib/api.ts`.

### The current season

Everything on a player or defense page (header totals and ranks, chart, averages,
consistency strip, game log) is the **current season** only. That is the season of the
sport's next game that hasn't finished (one in progress counts), or, once the schedule has
run out, of its latest game. So in the NBA offseason last season's final games are history,
not "the last 5/10 games": the page shows an empty state and the schedule until the
team's first game of the new season is played. The backend defines it once
(`get_current_season` in `app/services/players.py`).

`/players/{id}/stats` and `/defenses/{team_id}/stats` take `season=current` for that, or
`season=all` (the default) for every season, which is what models and other consumers
should ask for. The frontend pages ask for `current`. The players list still ranks by the
latest season that has stats, so NBA totals shown there are last season's until the new one
starts.

### Season totals and ranks

`GET /api/v1/players/{id}/season` and `GET /api/v1/defenses/{team_id}/season` return a
player's (or defense's) totals for the current season (see below), each stat with its rank
(1 = best), whether it is `tied`, and the `pool_size` it is ranked among. `stats` has every
stat column plus `fantasy_points`, scored under the `scoring` parameter (default scoring
when omitted). The response is `null` for a player who hasn't played yet.

"The same position" follows the position filters: QB, RB (with fullbacks), WR, TE and K
in the NFL; G, F and C in the NBA (folding in PG/SG and SF/PF); a position with no group of
its own (a linebacker) is ranked among players with that exact code; a defense is ranked
among the 32 defenses. Only players who actually played are ranked (an NBA row with no
minutes doesn't count). Fewer is better for turnovers, interceptions thrown, fumbles lost,
and a defense's points and yards allowed. The logic is in `app/services/season_summary.py`.

### Fantasy scoring config

A league's scoring is data: a `ScoringConfig` holds the per-stat weights for players
(`player_weights`), distance brackets for field goals made and missed
(`field_goal_made`, `field_goal_missed`), weights for a team defense
(`defense_weights`) and points-allowed brackets (`points_allowed`). A bracket is an
inclusive range with an open end allowed (`0-19`, `35+`); a value in no bracket scores
nothing. A config is validated when it is built: unknown stat names, overlapping
brackets, backwards ranges and NFL-only scoring on an NBA config are all rejected.
Missed shots and extra points are derived from attempts minus makes, so a league can
weight `field_goals_missed`, `free_throws_missed`, `extra_points_missed` and
`passing_incompletions`.

`default_config("NBA" | "NFL")` gives the FantasyIQ default. Its NFL kicker and defense
values are one real Yahoo league's settings (field goals 3/3/3/4/5 by distance, missed
-3/-3/-3/-2/-1, extra points +1/-1, sack 1, interception 2, fumble recovery 2, touchdown
6, safety 2, blocked kick 2, return touchdown 6, 4th-down stop 1, points allowed 10 down to
-4). `score_player_game`, `score_defense_game` and `kick_points` apply a config in Python,
and `list_players(..., scoring=config)` ranks a season under any config in SQL; a test pins
the two together. Not scored yet: extra points returned and three-and-outs, which aren't
stored.

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

The database tests hit a real Postgres (not sqlite/mocked) and assume it is empty, so they
never use the app's database: each run drops and recreates `fantasyiq_test` on the same
server, migrates it, and points the app at it (`tests/conftest.py`). The Postgres user needs
permission to create databases (the Compose one does), and the run refuses to reset any
database not named `fantasyiq_test`. In the Compose stack:

```bash
docker compose exec backend python -m pytest
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
