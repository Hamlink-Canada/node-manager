"""Run packaged Alembic migrations against the configured SQLite database."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from .database import create_database_engine, is_memory_database


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
