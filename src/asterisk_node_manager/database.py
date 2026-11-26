"""SQLAlchemy database setup. Schema evolution belongs in Alembic migrations."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker


Base = declarative_base()


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


def sqlite_snapshot(database: str | Path, directory: str | Path | None = None) -> Path:
    """Create a transactionally consistent SQLite copy using SQLite's backup API."""
    database = Path(database)
    target_dir = Path(directory) if directory is not None else database.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".node-manager-snapshot-", suffix=".sqlite3", dir=target_dir)
    os.close(fd)
    snapshot = Path(name)
    try:
        with sqlite3.connect(database) as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        stat_result = database.stat()
        os.chmod(snapshot, stat_result.st_mode & 0o777)
        try:
            os.chown(snapshot, stat_result.st_uid, stat_result.st_gid)
        except PermissionError:
            pass
        return snapshot
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise
