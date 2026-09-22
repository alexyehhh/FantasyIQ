"""
Engine and session factory.

`SessionLocal()` is how every script/job/test gets a database session:
the seed script, the ingestion pipelines, and the model tests all use
this rather than constructing their own engine.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
