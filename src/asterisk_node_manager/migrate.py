"""Run packaged Alembic migrations against the configured SQLite database."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_database(database: str | Path) -> None:
    package_dir = Path(__file__).resolve().parent
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(package_dir / "alembic.ini"))
    config.set_main_option("script_location", str(package_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{Path(database)}")
    command.upgrade(config, "head")
