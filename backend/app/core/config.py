"""
Typed, environment-driven application configuration.

Every other module reads settings from here (via `get_settings()`),
never directly from `os.environ`. This keeps configuration centralized,
validated, and easy to override in tests.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # Postgres (used from Milestone 2 onward; present now so the shape is stable)
    postgres_user: str = "fantasyiq"
    postgres_password: str = "fantasyiq"
    postgres_db: str = "fantasyiq"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # CORS: comma-separated list of allowed origins
    cors_origins: str = "http://localhost:3000"

    # NBA.com ingestion via nba_api (Milestone 3)
    nba_api_timeout_seconds: float = 30.0

    # NFL ingestion via ESPN's public site API
    nfl_api_timeout_seconds: float = 30.0

    # ESPN's public API publishes no rate limit, so requests are spaced at least this far apart
    # (process-wide) and paused entirely when ESPN answers 429/503 (data_pipeline/espn.py).
    espn_min_request_interval_seconds: float = 0.25

    # The background worker (data_pipeline/worker.py) is the only thing that calls ESPN; these are
    # how often each of its jobs runs. A game in progress is refreshed at most every cooldown.
    worker_live_interval_seconds: float = 15.0
    worker_injuries_interval_seconds: float = 900.0
    worker_directory_interval_seconds: float = 21600.0
    worker_backfill_interval_seconds: float = 3600.0
    # Saving each projection source's projections for upcoming games, to score them afterwards.
    # Hourly, so the last one before a game has most of the late injury and lineup news; a run
    # takes seconds and only stores lines that changed.
    worker_snapshots_interval_seconds: float = 3600.0
    # Retraining the projection models on every finished game (app/ml/retrain.py).
    worker_retrain_interval_seconds: float = 7 * 24 * 3600.0
    worker_backfill_games_per_run: int = 20
    live_refresh_cooldown_seconds: float = 30.0
    # Short, since one slow game shouldn't hold up the others being refreshed.
    live_refresh_timeout_seconds: float = 8.0

    # Sleeper's public API (projections by Rotowire). The API server calls it on demand and keeps
    # the answer in memory for the TTL; nothing from it is stored in the database.
    sleeper_projections_url: str = "https://api.sleeper.com/projections"
    sleeper_state_url: str = "https://api.sleeper.app/v1/state"
    sleeper_timeout_seconds: float = 15.0
    # Sleeper's player file (depth charts and injury news). It is ~15 MB and Sleeper asks for it to
    # be fetched sparingly, so it is kept for hours, not minutes.
    sleeper_players_url: str = "https://api.sleeper.app/v1/players"
    sleeper_players_ttl_seconds: float = 6 * 3600.0
    sleeper_cache_ttl_seconds: float = 900.0

    # Our projection model (app/ml): how far a first-choice backup behind a newly out NFL starter is
    # projected to close the gap to the starter's workload, from 0 (leave it to the model, which
    # learned about two thirds) to 1 (the full starter role, as Sleeper's projections assume).
    projection_first_choice_share: float = 0.9

    # The AI Analyst (Milestone 9, app/ai/) calls Gemini for tool-calling and explanations.
    # "gemini-flash-latest" tracks Google's current default Flash model, so this doesn't need
    # bumping as newer ones ship.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"
    # In-process limits on the analyst endpoint, to protect that quota (one request costs
    # several Gemini calls). These are conservative guesses, not Google's published numbers —
    # they stopped publishing a fixed table for the free tier. Check your actual limits at
    # https://aistudio.google.com/rate-limit and adjust.
    analyst_rate_limit_per_minute: int = 8
    analyst_rate_limit_per_day: int = 150

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached so Settings is only parsed/validated once per process."""
    return Settings()
