"""Human-readable node settings based on the upstream app_rpt examples."""

from __future__ import annotations

import json
from pathlib import Path


TRANSLATION_DIR = Path(__file__).with_name("translations")

_FIELD_DEFINITIONS = (
    {"key": "rxchannel", "group": "radio", "kind": "channel", "default": "Local/pseudo"},
    {"key": "duplex", "group": "radio", "kind": "choice", "default": "2",
     "choices": ("0", "1", "2", "3", "4")},
    {"key": "linktolink", "group": "radio", "kind": "boolean", "default": "no"},
    {"key": "linkmongain", "group": "radio", "kind": "number", "default": "0", "min": -40, "max": 12},
    {"key": "hangtime", "group": "timing", "kind": "number", "default": "5000", "min": 0, "max": 9999999},
    {"key": "althangtime", "group": "timing", "kind": "number", "default": "0", "min": 0, "max": 9999999},
    {"key": "totime", "group": "timing", "kind": "number", "default": "180000", "min": 0, "max": 9999999},
    {"key": "idrecording", "group": "identification", "kind": "text", "default": "|iNOTSET", "max": 200},
    {"key": "idtalkover", "group": "identification", "kind": "text", "default": "", "max": 200},
    {"key": "idtime", "group": "identification", "kind": "number", "default": "300000", "min": 0, "max": 9999999},
    {"key": "politeid", "group": "identification", "kind": "number", "default": "30000", "min": 0, "max": 9999999},
    {"key": "context", "group": "phone", "kind": "text", "default": "radio", "max": 80},
    {"key": "callerid", "group": "phone", "kind": "text", "default": '"Repeater" <0000000000>', "max": 120},
    {"key": "accountcode", "group": "phone", "kind": "text", "default": "RADIO", "max": 80},
    {"key": "unlinkedct", "group": "telemetry", "kind": "text", "default": "ct2", "max": 80},
    {"key": "remotect", "group": "telemetry", "kind": "text", "default": "ct3", "max": 80},
    {"key": "linkunkeyct", "group": "telemetry", "kind": "text", "default": "ct8", "max": 80},
    {"key": "holdofftelem", "group": "telemetry", "kind": "boolean", "default": "no"},
    {"key": "telemdefault", "group": "telemetry", "kind": "choice", "default": "2",
     "choices": ("0", "1", "2")},
    {"key": "telemdynamic", "group": "telemetry", "kind": "boolean", "default": "yes"},
    {"key": "parrot", "group": "telemetry", "kind": "choice", "default": "0",
     "choices": ("0", "1")},
    {"key": "parrottime", "group": "telemetry", "kind": "number", "default": "1000", "min": 0, "max": 9999999},
    {"key": "rxboost", "file": "simpleusb.conf", "group": "simpleusb", "kind": "boolean", "default": "no"},
    {"key": "carrierfrom", "file": "simpleusb.conf", "group": "simpleusb", "kind": "choice", "default": "usbinvert",
     "choices": ("no", "usb", "usbinvert")},
    {"key": "ctcssfrom", "file": "simpleusb.conf", "group": "simpleusb", "kind": "choice", "default": "usbinvert",
     "choices": ("no", "usb", "usbinvert")},
    {"key": "deemphasis", "file": "simpleusb.conf", "group": "simpleusb", "kind": "boolean", "default": "no"},
    {"key": "plfilter", "file": "simpleusb.conf", "group": "simpleusb", "kind": "boolean", "default": "yes"},
    {"key": "rxondelay", "file": "simpleusb.conf", "group": "simpleusb", "kind": "number", "default": "0", "min": 0, "max": 1000},
    {"key": "txoffdelay", "file": "simpleusb.conf", "group": "simpleusb", "kind": "number", "default": "0", "min": 0, "max": 1000},
    {"key": "invertptt", "file": "simpleusb.conf", "group": "simpleusb", "kind": "boolean", "default": "no"},
    {"key": "preemphasis", "file": "simpleusb.conf", "group": "simpleusb", "kind": "boolean", "default": "no"},
    {"key": "rxmixerset", "file": "simpleusb.conf", "group": "simpleusb", "kind": "number", "default": "500", "min": 0, "max": 999},
    {"key": "txmixaset", "file": "simpleusb.conf", "group": "simpleusb", "kind": "number", "default": "500", "min": 0, "max": 999},
    {"key": "txmixbset", "file": "simpleusb.conf", "group": "simpleusb", "kind": "number", "default": "500", "min": 0, "max": 999},
)

_BASIC_FIELDS = {"rxchannel", "duplex"}
NODE_CONFIG_FIELDS = {field["key"]: field for field in _FIELD_DEFINITIONS
                      if field.get("file", "rpt.conf") == "rpt.conf"}


def available_locales() -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in TRANSLATION_DIR.glob("*.json")))


def translate(locale: str, key: str) -> str:
    """Translate a message, falling back to English when a locale is incomplete."""
    english = _load_catalog("en")
    catalog = _load_catalog(locale)
    return catalog.get(key, english.get(key, key))


def node_field_groups(node_number: int, settings: dict[str, str], locale: str = "en") -> list[dict]:
    """Build display-ready form groups from the stable field definitions."""
    catalog = _load_catalog(locale)
    english = _load_catalog("en")
    groups: list[dict] = []
    by_name: dict[tuple[str, bool], dict] = {}
    selected_channel = str(settings.get("rxchannel", "Local/pseudo"))
    for definition in _FIELD_DEFINITIONS:
        if definition.get("file") == "simpleusb.conf" and not selected_channel.startswith("SimpleUSB/"):
            continue
        group_key = definition["group"]
        advanced = key_in_advanced(definition)
        group_id = (group_key, advanced)
        if group_id not in by_name:
            group = {"title": _message(f"group_{group_key}", locale, catalog, english), "fields": [],
                     "advanced": advanced}
            by_name[group_id] = group
            groups.append(group)
        key = definition["key"]
        value = str(settings.get(key, definition["default"]))
        kind = definition["kind"]
        existing_number = None
        if kind == "number":
            try:
                existing_number = int(value)
            except ValueError:
                pass
        if kind == "channel":
            channel_choices = [
                ("Local/pseudo", _message("channel_local", locale, catalog, english)),
                (f"SimpleUSB/{node_number}", _message("channel_simpleusb", locale, catalog, english)),
                (f"Radio/{node_number}", _message("channel_usbradio", locale, catalog, english)),
                (f"Voter/{node_number}", _message("channel_voter", locale, catalog, english)),
            ]
            if value not in {option[0] for option in channel_choices}:
                channel_choices.append((value, f"{value} ({_message('custom', locale, catalog, english)})"))
            choices = channel_choices
        elif kind == "choice":
            choices = [(choice, _message(f"{key}_option_{choice}", locale, catalog, english))
                       for choice in definition["choices"]]
            if value not in {option[0] for option in choices}:
                choices.append((value, f"{value} ({_message('custom', locale, catalog, english)})"))
        else:
            choices = []
        by_name[group_id]["fields"].append({
            **definition,
            "label": _message(f"field_{key}", locale, catalog, english),
            "help": _message(f"help_{key}", locale, catalog, english),
            "value": value,
            "choices": choices,
            "advanced": advanced,
            "browser_max": max(definition.get("max", 0), existing_number) if existing_number is not None else definition.get("max"),
            "browser_min": min(definition.get("min", 0), existing_number) if existing_number is not None else definition.get("min"),
        })
    return groups


def key_in_advanced(definition: dict) -> bool:
    return definition["key"] not in _BASIC_FIELDS and definition.get("file") != "simpleusb.conf"


def node_fields_for_file(file_name: str) -> set[str]:
    return {field["key"] for field in _FIELD_DEFINITIONS
            if field.get("file", "rpt.conf") == file_name}


def node_config_values(node) -> dict[str, str]:
    """Return typed node columns in their Asterisk configuration form."""
    result = {}
    for key, definition in NODE_CONFIG_FIELDS.items():
        value = getattr(node, key)
        if definition["kind"] == "boolean":
            result[key] = "yes" if value else "no"
        else:
            result[key] = str(value)
    return result


def apply_node_config_values(node, values: dict[str, str]) -> None:
    """Set known node columns from Asterisk-style string values."""
    for key, value in values.items():
        definition = NODE_CONFIG_FIELDS.get(key)
        if definition is None:
            continue
        if definition["kind"] == "boolean":
            value = str(value).lower() in {"yes", "true", "1", "on"}
        elif definition["kind"] == "number" or definition["kind"] == "choice" and key in {"duplex", "telemdefault", "parrot"}:
            value = int(value)
        setattr(node, key, value)


def validate_node_settings(form, node_number: int, existing: dict[str, str] | None = None) -> tuple[dict[str, str] | None, dict[str, str]]:
    """Validate named fields and return normalized Asterisk values by key."""
    values: dict[str, str] = {}
    errors: dict[str, str] = {}
    existing = existing or {}
    for definition in _FIELD_DEFINITIONS:
        key, kind = definition["key"], definition["kind"]
        raw = form.get(key, "")
        if key not in form:
            values[key] = existing.get(key, definition["default"])
            continue
        if kind == "channel":
            allowed = {"Local/pseudo", f"SimpleUSB/{node_number}", f"Radio/{node_number}",
                       f"Voter/{node_number}"}
            if raw not in allowed and raw != existing.get(key):
                errors[key] = "Choose a supported channel driver."
            else:
                values[key] = raw
        elif kind == "boolean":
            if raw not in {"yes", "no"}:
                errors[key] = "Choose yes or no."
            else:
                values[key] = raw
        elif kind == "choice":
            if raw not in definition["choices"] and raw != existing.get(key):
                errors[key] = "Choose one of the listed options."
            else:
                values[key] = raw
        elif kind == "number":
            if raw == existing.get(key):
                values[key] = raw
                continue
            try:
                number = int(raw)
                if not definition["min"] <= number <= definition["max"]:
                    raise ValueError
                values[key] = str(number)
            except (ValueError, TypeError):
                errors[key] = f"Enter a whole number from {definition['min']} to {definition['max']}."
        else:
            value = raw.strip()
            if ("\n" in value or "\r" in value or len(value) > definition["max"]):
                errors[key] = f"Enter at most {definition['max']} characters on one line."
            else:
                values[key] = value
    return (None, errors) if errors else (values, {})


def _message(key: str, locale: str, catalog: dict, english: dict) -> str:
    return catalog.get(key, english.get(key, key))


def _load_catalog(locale: str) -> dict[str, str]:
    path = TRANSLATION_DIR / f"{locale}.json"
    if not path.is_file():
        path = TRANSLATION_DIR / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))
