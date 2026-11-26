"""Simple parser for preserving Asterisk configuration sections and lines."""

from __future__ import annotations

import re

from .generate import GENERATED_FILES

SECRET_KEY = re.compile(r"(password|secret|token|credential|auth|api[_-]?key)", re.IGNORECASE)
SECRET_VALUE = "[hidden]"


def is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY.search(key))


def parse_config(filename: str, text: str) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    values: dict[str, dict[str, str]] = {}
    preserved: dict[str, list[str]] = {}
    section = ""
    recognized_file = filename in GENERATED_FILES
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            values.setdefault(section, {})
            preserved.setdefault(section, [])
        elif not stripped or stripped.startswith((";", "#")):
            preserved.setdefault(section, []).append(line)
        elif "=" in line and recognized_file:
            key, value = line.split("=", 1)
            values.setdefault(section, {})[key.strip()] = value.strip()
        else:
            preserved.setdefault(section, []).append(line)
    return values, preserved
