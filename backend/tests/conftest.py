"""Test setup: a database of its own, never the one the app runs on.

The database tests assume an empty database (they count rows and rank "every player"), and the
worker's leader lock lives in the database it uses, so running them against the development
database both fails them and risks its data. Instead every test run drops and recreates
`fantasyiq_test` on the same Postgres server and migrates it to the latest revision. This
happens before the app is imported, because the app reads its settings, once, at import.
"""

import os
from pathlib import Path

TEST_DATABASE = "fantasyiq_test"

os.environ["POSTGRES_DB"] = TEST_DATABASE

# Tests never wait on the pacing of requests to ESPN (they use fake transports anyway). Set before
# anything reads the settings, which are read once.
os.environ["ESPN_MIN_REQUEST_INTERVAL_SECONDS"] = "0"


def _recreate_test_database() -> None:
    import psycopg
    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings

    settings = get_settings()
    # Dropping a database is only ever done to one that is named as a test database.
    assert settings.postgres_db == TEST_DATABASE, "refusing to reset a non-test database"

    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname="postgres",
        autocommit=True,
    ) as connection:
        connection.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        connection.execute(f'CREATE DATABASE "{TEST_DATABASE}"')

    backend = Path(__file__).resolve().parents[1]
    # No ini file: alembic would otherwise reconfigure logging and print every migration.
    config = Config()
    config.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(config, "head")


def pytest_configure(config) -> None:
    _recreate_test_database()
