"""Network profile validation and startup discovery."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sqlalchemy import select

from .database import is_memory_database, session_factory
from .models import Network

logger = logging.getLogger(__name__)


def parse_network_profile(value: object) -> dict:
    """Validate and normalize a version 1 network profile."""
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "key", "name", "config"}
            or isinstance(value.get("schema_version"), bool)
            or value.get("schema_version") != 1):
        raise ValueError("Unsupported network profile schema")
    key, name, config = value["key"], value["name"], value["config"]
    if (not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,120}", key)
            or not isinstance(name, str) or not name.strip() or len(name) > 200
            or not isinstance(config, dict)):
        raise ValueError("Network profile needs a key, name, and object config")
    return {"schema_version": 1, "key": key, "name": name.strip(), "config": config}


def load_network_profiles(directory: str | Path, database: str | Path) -> int:
    """Read JSON profiles from a directory and insert or update them by stable key."""
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    imported = 0
    sessions = session_factory(database)
    try:
        with sessions.begin() as db:
            for path in sorted(directory.glob("*.json")):
                try:
                    profile = parse_network_profile(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, UnicodeError, json.JSONDecodeError,
                        ValueError, RecursionError) as exc:
                    logger.warning("Skipping network profile %s: %s", path, exc)
                    continue
                network = db.scalar(select(Network).where(Network.stable_key == profile["key"]))
                if network is None:
                    network = Network(stable_key=profile["key"], name=profile["name"],
                                      schema_version=1, config=profile["config"])
                    db.add(network)
                else:
                    network.name = profile["name"]
                    network.schema_version = 1
                    network.config = profile["config"]
                imported += 1
    finally:
        if not is_memory_database(database):
            sessions.kw["bind"].dispose()
    return imported
