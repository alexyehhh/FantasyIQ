"""
Declarative base for all ORM models.

Every model in app/db/models imports `Base` from here. Alembic's env.py
imports app.db.models (which imports every model, registering it on
Base.metadata) so autogenerate can see the full schema.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
