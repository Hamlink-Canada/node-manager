"""SQLAlchemy database setup. Schema evolution belongs in Alembic migrations."""

from __future__ import annotations

import os
import fcntl
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


Base = declarative_base()
_memory_engines: dict[str, Engine] = {}
_file_engines: dict[str, Engine] = {}


def is_memory_database(database: str | Path) -> bool:
    return str(database) == ":memory:" or str(database).startswith(":memory:")


def database_exists(database: str | Path) -> bool:
    return is_memory_database(database) or Path(database).is_file()


def create_database_engine(path: str | Path) -> Engine:
    if is_memory_database(path):
        key = str(path)
        if key not in _memory_engines:
            engine = create_engine("sqlite://", future=True, poolclass=StaticPool,
                                   connect_args={"check_same_thread": False})
            _enable_foreign_keys(engine)
            _memory_engines[key] = engine
        return _memory_engines[key]

    db_path = Path(path).resolve()
    key = str(db_path)
    if key in _file_engines:
        return _file_engines[key]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    _enable_foreign_keys(engine)
    _file_engines[key] = engine
    return engine


def _enable_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()



def dispose_database_engine(database: str | Path) -> None:
    # Disposing a StaticPool-backed in-memory engine would close the only
    # connection and erase the demo database between requests.
    if not is_memory_database(database):
        create_database_engine(database).dispose()


def acquire_database_write_lock(database: str | Path) -> int | None:
    """Acquire an interprocess lock for file-backed database mutations."""
    if is_memory_database(database):
        return None
    db_path = Path(database)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = db_path.with_name(db_path.name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except Exception:
        os.close(fd)
        raise
    return fd


def release_database_write_lock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


@contextmanager
def database_write_lock(database: str | Path):
    fd = acquire_database_write_lock(database)
    try:
        yield
    finally:
        if fd is not None:
            release_database_write_lock(fd)


def session_factory(path: str | Path) -> sessionmaker:
    return sessionmaker(bind=create_database_engine(path), expire_on_commit=False)


def sqlite_snapshot(database: str | Path, directory: str | Path | None = None) -> Path:
    """Create a transactionally consistent SQLite copy using SQLite's backup API."""
    database = Path(database)
    database_path = None if is_memory_database(database) else Path(database)
    target_dir = Path(directory) if directory is not None else (
        database_path.parent if database_path is not None else Path(tempfile.gettempdir()))
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".node-manager-snapshot-", suffix=".sqlite3", dir=target_dir)
    os.close(fd)
    snapshot = Path(name)
    try:
        if database_path is None:
            engine_connection = create_database_engine(database).raw_connection()
            try:
                dbapi_connection = (getattr(engine_connection, "driver_connection", None)
                                    or engine_connection.connection)
                with sqlite3.connect(snapshot) as target:
                    dbapi_connection.backup(target)
            finally:
                engine_connection.close()
        else:
            with sqlite3.connect(database_path) as source, sqlite3.connect(snapshot) as target:
                source.backup(target)
            stat_result = database_path.stat()
            try:
                os.chown(snapshot, stat_result.st_uid, stat_result.st_gid)
            except PermissionError:
                pass
            else:
                os.chmod(snapshot, stat_result.st_mode & 0o777)
        return snapshot
    except Exception:
        snapshot.unlink(missing_ok=True)
        raise


def restore_sqlite_snapshot(database: str | Path, snapshot: str | Path) -> None:
    """Restore a SQLite snapshot to a file database or the demo's memory DB."""
    if is_memory_database(database):
        engine_connection = create_database_engine(database).raw_connection()
        try:
            dbapi_connection = (getattr(engine_connection, "driver_connection", None)
                                or engine_connection.connection)
            with sqlite3.connect(snapshot) as source:
                source.backup(dbapi_connection)
        finally:
            engine_connection.close()
    else:
        os.replace(snapshot, database)
