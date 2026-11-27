import os
import sqlite3
import stat

from asterisk_node_manager.database import create_database_engine, sqlite_snapshot
from sqlalchemy.pool import NullPool


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
