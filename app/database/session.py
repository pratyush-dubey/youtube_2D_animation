"""
Database engine and session factory.
Import get_session() wherever you need a DB session.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings
from app.database.models import Base

# SQLite: enable WAL mode and foreign keys for better concurrency + integrity
_DB_URL = f"sqlite:///{settings.db_path}"

engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # Controlled via sqlalchemy.engine logger level, not here
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context-manager that yields a transactional session and auto-commits/rolls back."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
