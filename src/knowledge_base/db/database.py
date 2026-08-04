"""
SQLite engine and session factory.

Sync engine is used by the pipeline scripts.
Async engine is used by FastAPI endpoints.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session

from src.knowledge_base.config import get_settings
from src.knowledge_base.db.models import Base

settings = get_settings()


def _db_path() -> str:
    path = Path(settings.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@lru_cache
def get_engine():
    url = f"sqlite:///{_db_path()}"
    engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})

    # Enable WAL mode and foreign keys for every connection
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

    return engine


@lru_cache
def get_async_engine():
    url = f"sqlite+aiosqlite:///{_db_path()}"
    return create_async_engine(url, echo=False)


def get_session() -> Session:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return factory()


def get_async_session() -> AsyncSession:
    factory = async_sessionmaker(bind=get_async_engine(), expire_on_commit=False)
    return factory()


def init_db():
    """Create all tables (idempotent — safe to call on every startup)."""
    Base.metadata.create_all(get_engine())
