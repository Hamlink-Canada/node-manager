from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


import pytest
from cryptography.fernet import Fernet

from asterisk_node_manager.encryption import configure_encryption_key
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.migrate import upgrade_database


# The app's production entry points require an operator-supplied key. Tests use
# a process-local key so fixtures can exercise the ORM without deployment config.
configure_encryption_key(Fernet.generate_key())


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "manager.sqlite3"
    upgrade_database(path)
    yield path
    session_factory(path).kw["bind"].dispose()


@pytest.fixture
def db_session(database):
    sessions = session_factory(database)
    try:
        with sessions() as session:
            yield session
    finally:
        sessions.kw["bind"].dispose()
