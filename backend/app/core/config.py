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
    worker_backfill_games_per_run: int = 20
    live_refresh_cooldown_seconds: float = 30.0
    # Short, since one slow game shouldn't hold up the others being refreshed.
    live_refresh_timeout_seconds: float = 8.0

    # Sleeper's public API (projections by Rotowire). The API server calls it on demand and keeps
    # the answer in memory for the TTL; nothing from it is stored in the database.
    sleeper_projections_url: str = "https://api.sleeper.com/projections"
    sleeper_state_url: str = "https://api.sleeper.app/v1/state"
    sleeper_timeout_seconds: float = 15.0
    sleeper_cache_ttl_seconds: float = 900.0

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
