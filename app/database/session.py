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
    _migrate_scene_timeline_columns()


def _migrate_scene_timeline_columns() -> None:
    """Small idempotent SQLite migration for existing installations."""
    additions = {
        "shot_plan": "JSON",
        "layer_graph": "JSON",
        "animation_timeline": "JSON",
        "animation_quality": "JSON",
        "render_mode": "VARCHAR(40)",
        "random_seed": "INTEGER",
    }
    with engine.begin() as connection:
        existing = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(scenes)").fetchall()
        }
        for name, sql_type in additions.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE scenes ADD COLUMN {name} {sql_type}")


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
