"""SQLAlchemy database setup. Schema evolution belongs in Alembic migrations."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for persistent application models."""


def create_database_engine(path: str | Path) -> Engine:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def session_factory(path: str | Path) -> sessionmaker:
    return sessionmaker(bind=create_database_engine(path), expire_on_commit=False)
