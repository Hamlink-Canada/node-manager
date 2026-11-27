import os
import sqlite3
import stat

from sqlalchemy.pool import NullPool

from asterisk_node_manager.database import (
    acquire_database_write_lock,
    create_database_engine,
    release_database_write_lock,
    sqlite_snapshot,
)


def test_snapshot_stays_private_if_ownership_cannot_be_copied(monkeypatch, tmp_path):
    database = tmp_path / "manager.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
    database.chmod(0o640)

    def reject_chown(*_args):
        raise PermissionError("not privileged")

    monkeypatch.setattr(os, "chown", reject_chown)
    snapshot = sqlite_snapshot(database)
    try:
        assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    finally:
        snapshot.unlink(missing_ok=True)


def test_file_database_engine_does_not_retain_connections(tmp_path):
    engine = create_database_engine(tmp_path / "manager.sqlite3")
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        engine.dispose()


def test_database_write_lock_uses_database_ownership_and_reuses_sidecar(tmp_path):
    database = tmp_path / "manager.sqlite3"
    database.touch()
    lock_path = tmp_path / "manager.sqlite3.lock"

    first_fd = acquire_database_write_lock(database)
    first_stat = lock_path.stat()
    release_database_write_lock(first_fd)
    second_fd = acquire_database_write_lock(database)
    try:
        second_stat = lock_path.stat()
        assert first_stat.st_ino == second_stat.st_ino
        assert (second_stat.st_uid, second_stat.st_gid) == (database.stat().st_uid,
                                                           database.stat().st_gid)
    finally:
        release_database_write_lock(second_fd)
