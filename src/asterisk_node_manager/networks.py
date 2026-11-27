"""Network profile validation and startup discovery."""

from __future__ import annotations

import json
import logging
import ipaddress
import re
from urllib.parse import urlsplit
from pathlib import Path

from sqlalchemy import select

from .database import is_memory_database, session_factory
from .models import Network

logger = logging.getLogger(__name__)

NETWORK_DEFAULTS = {
    "registration_method": "http",
    "http_registration_server": "",
    "iax_registration_server": "",
    "iax_registration_port": 4569,
    "stats_enabled": False,
    "stats_post_url": "",
    "stats_post_interval": 60,
    "node_lookup_method": "both",
    "dns_node_domain": "",
    "max_dns_node_length": 6,
    "external_node_file": "",
}

NETWORK_FIELD_DEFINITIONS = (
    {"key": "registration_method", "label": "Registration method", "type": "choice",
     "choices": (("http", "HTTP"), ("iax", "IAX"), ("none", "Disabled")),
     "help": "Choose the network registration transport. Use one method; HTTP is the current AllStarLink default."},
    {"key": "http_registration_server", "label": "HTTP registration server", "type": "text",
     "help": "Host name (optionally with port) used for HTTP node registration."},
    {"key": "iax_registration_server", "label": "IAX registration server", "type": "text",
     "help": "Host name used for legacy IAX registration. Set its UDP port in the next field."},
    {"key": "iax_registration_port", "label": "IAX registration port", "type": "number",
     "min": 1, "max": 65535, "help": "UDP port used by the IAX registration server."},
    {"key": "stats_enabled", "label": "Post node status", "type": "boolean",
     "help": "Send node status updates to this network's statistics service."},
    {"key": "stats_post_url", "label": "Status reporting URL", "type": "url",
     "help": "Full URL that accepts app_rpt node status updates."},
    {"key": "stats_post_interval", "label": "Status reporting interval (seconds)", "type": "number",
     "min": 30, "max": 600, "help": "How often connected node links are reported. Key-up and key-down changes are reported separately."},
    {"key": "node_lookup_method", "label": "Node lookup method", "type": "choice",
     "choices": (("dns", "DNS only"), ("file", "External node file only"),
                 ("both", "DNS, then external node file")),
     "help": "Choose how app_rpt resolves remote node numbers when no static entry is present."},
    {"key": "dns_node_domain", "label": "DNS node domain", "type": "text",
     "help": "DNS domain used to resolve this network's node numbers."},
    {"key": "max_dns_node_length", "label": "Maximum DNS node ID length", "type": "number",
     "min": 1, "max": 12, "help": "Maximum number of digits in a node ID queried through DNS."},
    {"key": "external_node_file", "label": "External node file path", "type": "text",
     "help": "Local file path used when node lookup includes the external node file."},
)


def network_fields(profile: dict | object | None = None) -> dict:
    """Return the declared network settings with their stored or default values."""
    result = {}
    for key, default in NETWORK_DEFAULTS.items():
        value = profile.get(key, default) if isinstance(profile, dict) else getattr(profile, key, default)
        result[key] = value
    return result


def _validate_host(value: str, field_name: str, allow_port: bool = False) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) > 255 or any(char.isspace() for char in value) or "://" in value:
        raise ValueError(f"{field_name} must be a host name, optionally followed by a port")
    parsed = urlsplit(f"//{value}")
    try:
        valid = bool(parsed.hostname) and (allow_port or parsed.port is None)
        valid = valid and (parsed.port is None or 1 <= parsed.port <= 65535)
    except ValueError:
        valid = False
    if not valid or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError(f"{field_name} must be a host name, optionally followed by a port")
    hostname = parsed.hostname
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if (len(hostname) > 253 or any(not re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in hostname.rstrip(".").split("."))):
            raise ValueError(f"{field_name} must be a valid host name or IP address") from None
    return value


def parse_network_profile(value: object) -> dict:
    """Validate and normalize a version 2 profile with explicit service fields."""
    expected_keys = {"schema_version", "key", "name", *NETWORK_DEFAULTS}
    if (not isinstance(value, dict)
            or set(value) != expected_keys
            or isinstance(value.get("schema_version"), bool)
            or value.get("schema_version") != 2):
        raise ValueError("Unsupported network profile schema")
    key, name = value["key"], value["name"]
    if (not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,120}", key)
            or not isinstance(name, str) or not name.strip() or len(name) > 200):
        raise ValueError("Network profile needs a valid key and name")
    normalized = {"schema_version": 2, "key": key, "name": name.strip()}
    fields = {item["key"]: item for item in NETWORK_FIELD_DEFINITIONS}
    for key, default in NETWORK_DEFAULTS.items():
        raw = value[key]
        definition = fields[key]
        if definition["type"] == "boolean":
            if not isinstance(raw, bool):
                raise ValueError(f"{key} must be true or false")
        elif definition["type"] == "number":
            if isinstance(raw, bool):
                raise ValueError(f"{key} must be a number")
            try:
                raw = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a whole number") from None
            if not definition["min"] <= raw <= definition["max"]:
                raise ValueError(f"{key} must be from {definition['min']} to {definition['max']}")
        else:
            if not isinstance(raw, str):
                raise ValueError(f"{key} must be text")
            raw = raw.strip()
            if len(raw) > (500 if key in {"stats_post_url", "external_node_file"} else 255):
                raise ValueError(f"{key} is too long")
            if any(ord(char) < 32 or ord(char) == 127 for char in raw):
                raise ValueError(f"{key} cannot contain control characters")
            if definition["type"] == "choice" and raw not in {choice[0] for choice in definition["choices"]}:
                raise ValueError(f"{key} has an unsupported value")
            if key in {"http_registration_server", "iax_registration_server", "dns_node_domain"}:
                raw = _validate_host(raw, definition["label"],
                                     allow_port=key == "http_registration_server")
            if key == "stats_post_url" and raw:
                parsed = urlsplit(raw)
                try:
                    port_valid = parsed.port is None or 1 <= parsed.port <= 65535
                except ValueError:
                    port_valid = False
                if (parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname
                        or parsed.username is not None or parsed.password is not None or parsed.fragment
                        or not port_valid or any(char.isspace() for char in raw)):
                    raise ValueError("stats_post_url must be an HTTP or HTTPS URL")
        normalized[key] = raw
    return normalized


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
                                      schema_version=2, **network_fields(profile))
                    db.add(network)
                else:
                    network.name = profile["name"]
                    network.schema_version = 2
                    for key, value in network_fields(profile).items():
                        setattr(network, key, value)
                imported += 1
    finally:
        if not is_memory_database(database):
            sessions.kw["bind"].dispose()
    return imported
