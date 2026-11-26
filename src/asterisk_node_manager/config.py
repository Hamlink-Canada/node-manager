"""Runtime configuration loading."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: Path = Path("/var/lib/asterisk-node-manager/manager.sqlite3")
    asterisk_directory: Path = Path("/etc/asterisk")
    writer_socket: Path = Path("/run/asterisk-node-manager/writer.sock")
    writer_allowlist: Path = Path("/etc/asterisk-node-manager/writers")
    asterisk_cli: Path = Path("/usr/sbin/asterisk")
    listen_address: str = "127.0.0.1"
    port: int = 8765
    pam_service: str = "asterisk-node-manager"
    secret_key_file: Path = Path("/etc/asterisk-node-manager/secret-key")


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path or os.environ.get("ASTNODE_CONFIG", "node-manager.toml"))
    if not config_path.exists():
        return Settings()
    with config_path.open("rb") as stream:
        raw = tomllib.load(stream)
    paths = raw.get("paths", {})
    web = raw.get("web", {})
    return Settings(
        database=Path(paths.get("database", Settings.database)),
        asterisk_directory=Path(paths.get("asterisk_directory", Settings.asterisk_directory)),
        writer_socket=Path(paths.get("writer_socket", Settings.writer_socket)),
        writer_allowlist=Path(paths.get("writer_allowlist", Settings.writer_allowlist)),
        asterisk_cli=Path(paths.get("asterisk_cli", Settings.asterisk_cli)),
        listen_address=str(web.get("listen_address", "127.0.0.1")),
        port=int(web.get("port", 8765)),
        pam_service=str(web.get("pam_service", "asterisk-node-manager")),
        secret_key_file=Path(web.get("secret_key_file", Settings.secret_key_file)),
    )
