"""Runtime configuration loading."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: Path | str = Path("/var/lib/asterisk-node-manager/manager.sqlite3")
    asterisk_directory: Path = Path("/etc/asterisk")
    writer_socket: Path = Path("/run/asterisk-node-manager/writer.sock")
    writer_allowlist: Path = Path("/etc/asterisk-node-manager/writers")
    asterisk_cli: Path = Path("/usr/sbin/asterisk")
    listen_address: str = "127.0.0.1"
    port: int = 8765
    pam_service: str = "asterisk-node-manager"
    secret_key_file: Path = Path("/etc/asterisk-node-manager/secret-key")
    demo_mode: bool = False
    demo_output_directory: Path = Path("/tmp/asterisk-node-manager-demo")


def load_settings(path: str | Path | None = None) -> Settings:
    explicit_config = path is not None or "ASTNODE_CONFIG" in os.environ
    config_path = Path(path or os.environ.get("ASTNODE_CONFIG", "node-manager.toml"))
    if explicit_config and not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    raw = {}
    if config_path.exists():
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
    paths = raw.get("paths", {})
    web = raw.get("web", {})
    demo_mode = os.environ.get("ASTNODE_DEMO", str(web.get("demo_mode", "false"))).lower() in {
        "1", "true", "yes", "on"}
    # Demo data must never touch a configured production database. SQLite's
    # in-memory database is scoped to this application process and disappears
    # when it exits.
    if demo_mode:
        database: Path | str = ":memory:"
    else:
        database = Path(os.environ.get("ASTNODE_DATABASE", paths.get("database", Settings.database)))
    return Settings(
        database=database,
        asterisk_directory=Path(os.environ.get(
            "ASTNODE_ASTERISK_DIRECTORY", paths.get("asterisk_directory", Settings.asterisk_directory))),
        writer_socket=Path(os.environ.get(
            "ASTNODE_WRITER_SOCKET", paths.get("writer_socket", Settings.writer_socket))),
        writer_allowlist=Path(os.environ.get(
            "ASTNODE_WRITER_ALLOWLIST", paths.get("writer_allowlist", Settings.writer_allowlist))),
        asterisk_cli=Path(os.environ.get("ASTNODE_ASTERISK_CLI", paths.get("asterisk_cli", Settings.asterisk_cli))),
        listen_address=str(os.environ.get("ASTNODE_LISTEN_ADDRESS", web.get("listen_address", "127.0.0.1"))),
        port=int(os.environ.get("ASTNODE_PORT", web.get("port", 8765))),
        pam_service=str(os.environ.get("ASTNODE_PAM_SERVICE", web.get("pam_service", "asterisk-node-manager"))),
        secret_key_file=Path(os.environ.get(
            "ASTNODE_SECRET_KEY_FILE", web.get("secret_key_file", Settings.secret_key_file))),
        demo_mode=demo_mode,
        demo_output_directory=Path(os.environ.get(
            "ASTNODE_DEMO_OUTPUT_DIRECTORY", paths.get("demo_output_directory",
                "/tmp/asterisk-node-manager-demo"))),
    )
