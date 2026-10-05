"""SQLite engine/session wiring for the Fauna wildlife journal."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("FAUNA_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = Path(os.getenv("FAUNA_UPLOAD_DIR", BASE_DIR / "photos"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("FAUNA_DATABASE_URL", f"sqlite:///{DATA_DIR / 'fauna.db'}")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    """Create tables and bring older databases up to date (ADD-only)."""
    from app import models  # noqa: F401  (ensure models are registered)
    from app.models import Base

    Base.metadata.create_all(engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    _apply_column_migrations()
    _backfill_photo_rows()


def _backfill_photo_rows() -> None:
    """One-time data backfill: observations that predate the multi-photo
    table keep their cover on observations.photo_path — give each one a
    matching row in observation_photos so galleries/lightboxes see them.
    Idempotent: only inserts where no row exists for that photo."""
    with engine.connect() as conn:
        conn.exec_driver_sql(
            """
            INSERT INTO observation_photos (observation_id, photo_path, created_at)
            SELECT o.id, o.photo_path, o.created_at
            FROM observations o
            WHERE o.photo_path IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM observation_photos p
                WHERE p.observation_id = o.id AND p.photo_path = o.photo_path
              )
            """
        )
        conn.commit()


def _apply_column_migrations() -> None:
    """ADD any model columns missing from existing tables (SQLite only).

    Mirrors Verdant's discipline: migrations only ever ADD columns, and every
    column stays nullable so ADD COLUMN is always safe.
    """
    from app.models import Base

    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            present = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")}
            for column in table.columns:
                if column.name not in present:
                    coltype = column.type.compile(dialect=engine.dialect)
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table.name} ADD COLUMN {column.name} {coltype}"
                    )
