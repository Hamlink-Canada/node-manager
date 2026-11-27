"""Dynaconf-backed runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dynaconf import Dynaconf
from dynaconf.loaders import env_loader

DEFAULTS = {
    "paths": {
        "database": "/var/lib/asterisk-node-manager/manager.sqlite3",
        "asterisk_directory": "/etc/asterisk",
        "writer_socket": "/run/asterisk-node-manager/writer.sock",
        "writer_allowlist": "/etc/asterisk-node-manager/writers",
        "network_profiles_directory": "/etc/asterisk-node-manager/networks",
        "asterisk_socket": "/var/run/asterisk/asterisk.ctl",
        "demo_output_directory": "/tmp/asterisk-node-manager-demo",
    },
    "web": {
        "listen_address": "127.0.0.1",
        "port": 8765,
        "pam_service": "asterisk-node-manager",
        "secret_key_file": "/etc/asterisk-node-manager/secret-key",
        "demo_mode": False,
    },
    "networks": {
        "profiles_enabled": False,
        "default_network": "allstarlink",
    },
}

@dataclass(frozen=True)
class Settings:
    """Typed settings adapter used by application services and tests."""

    database: Path | str = Path(DEFAULTS["paths"]["database"])
    asterisk_directory: Path = Path(DEFAULTS["paths"]["asterisk_directory"])
    writer_socket: Path = Path(DEFAULTS["paths"]["writer_socket"])
    writer_allowlist: Path = Path(DEFAULTS["paths"]["writer_allowlist"])
    network_profiles_directory: Path = Path(DEFAULTS["paths"]["network_profiles_directory"])
    asterisk_socket: Path = Path(DEFAULTS["paths"]["asterisk_socket"])
    listen_address: str = DEFAULTS["web"]["listen_address"]
    port: int = DEFAULTS["web"]["port"]
    pam_service: str = DEFAULTS["web"]["pam_service"]
    secret_key_file: Path = Path(DEFAULTS["web"]["secret_key_file"])
    demo_mode: bool = DEFAULTS["web"]["demo_mode"]
    demo_output_directory: Path = Path(DEFAULTS["paths"]["demo_output_directory"])
    network_profiles_enabled: bool = DEFAULTS["networks"]["profiles_enabled"]
    default_network: str = DEFAULTS["networks"]["default_network"]


def load_settings(path: str | Path | None = None) -> Settings:
    """Load defaults, the optional TOML file, ASTNODE environment, and demo safety."""
    environment_path = os.environ.get("ASTNODE_CONFIG")
    explicit_config = path is not None or environment_path is not None
    config_path = Path(path or environment_path or "node-manager.toml")
    if explicit_config and not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    settings = Dynaconf(
        envvar_prefix="ASTNODE",
        environments=False,
        merge_enabled=True,
        settings_files=[],
        load_dotenv=False,
    )
    settings.update(DEFAULTS)
    if config_path.is_file():
        settings.load_file(path=str(config_path))

    # Defaults first, file values second, environment overrides last.
    env_loader.load(settings, env="ASTNODE")

    demo_mode = _as_bool(settings.WEB.DEMO_MODE, "web.demo_mode")
    network_profiles_enabled = _as_bool(settings.NETWORKS.PROFILES_ENABLED,
                                        "networks.profiles_enabled")
    default_network_value = settings.NETWORKS.DEFAULT_NETWORK
    if not isinstance(default_network_value, str):
        raise TypeError("networks.default_network must be a profile key string")
    default_network = default_network_value.strip()
    if not default_network:
        raise ValueError("networks.default_network must not be empty")
    if demo_mode:
        # Demo data must never touch a configured production database. SQLite's
        # in-memory database is scoped to this application process.
        database: Path | str = ":memory:"
    else:
        database = _path(settings.PATHS.DATABASE, "paths.database")

    port_value = settings.WEB.PORT
    if isinstance(port_value, bool) or not isinstance(port_value, (int, str)):
        raise TypeError("web.port must be an integer from 1 to 65535")
    try:
        port = int(port_value)
    except (TypeError, ValueError) as error:
        raise ValueError("web.port must be an integer from 1 to 65535") from error
    if not 1 <= port <= 65535:
        raise ValueError("web.port must be an integer from 1 to 65535")

    return Settings(
        database=database,
        asterisk_directory=_path(settings.PATHS.ASTERISK_DIRECTORY, "paths.asterisk_directory"),
        writer_socket=_path(settings.PATHS.WRITER_SOCKET, "paths.writer_socket"),
        writer_allowlist=_path(settings.PATHS.WRITER_ALLOWLIST, "paths.writer_allowlist"),
        network_profiles_directory=_path(settings.PATHS.NETWORK_PROFILES_DIRECTORY,
                                          "paths.network_profiles_directory"),
        asterisk_socket=_path(settings.PATHS.ASTERISK_SOCKET, "paths.asterisk_socket"),
        listen_address=str(settings.WEB.LISTEN_ADDRESS),
        port=port,
        pam_service=str(settings.WEB.PAM_SERVICE),
        secret_key_file=_path(settings.WEB.SECRET_KEY_FILE, "web.secret_key_file"),
        demo_mode=demo_mode,
        demo_output_directory=_path(settings.PATHS.DEMO_OUTPUT_DIRECTORY,
                                     "paths.demo_output_directory"),
        network_profiles_enabled=network_profiles_enabled,
        default_network=default_network,
    )


def _path(value: str | Path, name: str) -> Path:
    if not str(value).strip():
        raise ValueError(f"{name} must not be empty")
    return Path(value)


def _as_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{name} must be a boolean")
