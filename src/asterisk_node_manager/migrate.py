"""Run packaged Alembic migrations against the configured SQLite database."""

from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from .database import create_database_engine, is_memory_database


def validate_database_backup(path: str | Path) -> bool:
    """Return whether a SQLite file is intact and carries known app migration metadata."""
    try:
        with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                return False
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if version is None:
                return False
        scripts = ScriptDirectory(str(Path(__file__).resolve().parent / "migrations"))
        return version[0] in {revision.revision for revision in scripts.walk_revisions()}
    except (sqlite3.Error, LookupError, TypeError):
        return False


def upgrade_database(database: str | Path) -> None:
    package_dir = Path(__file__).resolve().parent
    config = Config(str(package_dir / "alembic.ini"))
    config.set_main_option("script_location", str(package_dir / "migrations"))
    engine = create_database_engine(database)
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    if not is_memory_database(database):
        engine.dispose()
