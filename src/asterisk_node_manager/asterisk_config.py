"""Simple parser for preserving Asterisk configuration sections and lines."""

from __future__ import annotations

import re

from .generate import GENERATED_FILES

SECRET_KEY = re.compile(r"(password|secret|token|credential|auth|api[_-]?key|^register$)", re.IGNORECASE)
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
        header = re.match(r"^\[([^]]+)\]((?:\([^)]*\))?)\s*(?:[;#].*)?$", stripped)
        if header:
            section = header.group(1).strip() + header.group(2)
            values.setdefault(section, {})
            preserved.setdefault(section, [])
        elif not stripped or stripped.startswith((";", "#")):
            preserved.setdefault(section, []).append(line)
        elif recognized_file and re.match(r"^\s*[^=]+\s*(?:=>|=)", line):
            match = re.match(r"^\s*(.*?)\s*(?:=>|=)\s*(.*?)\s*$", line)
            if match:
                key, value = match.groups()
                value, comment = _split_inline_comment(value)
                if key.strip().lower() in {
                    "allow", "exten", "load", "noload", "register", "require", "same",
                }:
                    preserved.setdefault(section, []).append(line)
                else:
                    values.setdefault(section, {})[key.strip()] = value
                    if comment:
                        preserved.setdefault(section, []).append(comment)
            else:
                preserved.setdefault(section, []).append(line)
        else:
            preserved.setdefault(section, []).append(line)
    return values, preserved


def _split_inline_comment(value: str) -> tuple[str, str | None]:
    """Split Asterisk's whitespace-delimited inline comment from an assignment."""
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
            continue
        if char == ";" and not quoted:
            return value[:index].rstrip(), value[index:].strip()
    return value.strip(), None
