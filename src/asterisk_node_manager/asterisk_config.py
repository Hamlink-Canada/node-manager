"""Simple parser for preserving Asterisk configuration sections and lines."""

from __future__ import annotations

import re

from .generate import GENERATED_FILES

SECRET_KEY = re.compile(r"(password|secret|token|credential|auth|api[_-]?key|^register$)", re.IGNORECASE)
SECRET_VALUE = "[hidden]"


def is_asterisk_include(line: str) -> bool:
    """Return whether a hash-prefixed line is an Asterisk include directive."""
    return bool(re.match(r"^\s*#(?:try)?include\b", line, re.IGNORECASE))


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
                    "allow", "disallow", "exten", "load", "noload", "register", "require", "same",
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


def expand_asterisk_inheritance(values: dict[str, dict[str, str]],
                                preserved: dict[str, list[str]]) -> None:
    """Materialize simple Asterisk section inheritance before database import."""
    sections = set(values) | set(preserved)
    templates = {section[:-3]: section for section in sections if section.endswith("(!)")}
    for section in list(sections):
        match = re.fullmatch(r"(.+)\(([^()]*)\)", section)
        if match is None or match.group(2) not in templates:
            continue
        parent = templates[match.group(2)]
        child_values = values.setdefault(section, {})
        for key, value in values.get(parent, {}).items():
            child_values.setdefault(key, value)
        parent_lines = preserved.get(parent, [])
        child_lines = preserved.get(section, [])
        preserved[section] = [*parent_lines, *child_lines]


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
