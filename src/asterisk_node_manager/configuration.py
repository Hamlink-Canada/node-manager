"""Human-readable node settings based on the upstream app_rpt examples."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
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
    {"key": "devstr", "file": "simpleusb.conf", "group": "simpleusb", "kind": "text", "default": "", "max": 200},
    {"key": "serial", "file": "simpleusb.conf", "group": "simpleusb", "kind": "text", "default": "", "max": 200},
    {"key": "rxboost", "file": "usbradio.conf", "group": "usbradio", "kind": "boolean", "default": "yes"},
    {"key": "carrierfrom", "file": "usbradio.conf", "group": "usbradio", "kind": "choice", "default": "dsp",
     "choices": ("no", "usb", "usbinvert", "dsp", "vox", "pp", "ppinvert")},
    {"key": "ctcssfrom", "file": "usbradio.conf", "group": "usbradio", "kind": "choice", "default": "dsp",
     "choices": ("no", "usb", "usbinvert", "dsp", "pp", "ppinvert")},
    {"key": "rxdemod", "file": "usbradio.conf", "group": "usbradio", "kind": "choice", "default": "flat",
     "choices": ("no", "speaker", "flat")},
    {"key": "rxmixerset", "file": "usbradio.conf", "group": "usbradio", "kind": "number", "default": "500", "min": 0, "max": 999},
    {"key": "rxsquelchadj", "file": "usbradio.conf", "group": "usbradio", "kind": "number", "default": "500", "min": 0, "max": 999},
    {"key": "rxvoiceadj", "file": "usbradio.conf", "group": "usbradio", "kind": "decimal", "default": "0.5", "min": 0, "max": 999},
    {"key": "rxctcssadj", "file": "usbradio.conf", "group": "usbradio", "kind": "decimal", "default": "0.5", "min": 0, "max": 999},
    {"key": "txmixaset", "file": "usbradio.conf", "group": "usbradio", "kind": "number", "default": "500", "min": 0, "max": 999},
    {"key": "txmixbset", "file": "usbradio.conf", "group": "usbradio", "kind": "number", "default": "500", "min": 0, "max": 999},
    {"key": "txctcssadj", "file": "usbradio.conf", "group": "usbradio", "kind": "number", "default": "200", "min": 0, "max": 999},
    {"key": "txboost", "file": "usbradio.conf", "group": "usbradio", "kind": "boolean", "default": "no"},
    {"key": "txprelim", "file": "usbradio.conf", "group": "usbradio", "kind": "boolean", "default": "yes"},
    {"key": "txlimonly", "file": "usbradio.conf", "group": "usbradio", "kind": "boolean", "default": "yes"},
    {"key": "txtoctype", "file": "usbradio.conf", "group": "usbradio", "kind": "choice", "default": "notone",
     "choices": ("no", "phase", "notone")},
    {"key": "txmixa", "file": "usbradio.conf", "group": "usbradio", "kind": "choice", "default": "composite",
     "choices": ("no", "voice", "tone", "composite", "auxvoice")},
    {"key": "txmixb", "file": "usbradio.conf", "group": "usbradio", "kind": "choice", "default": "no",
     "choices": ("no", "voice", "tone", "composite", "auxvoice")},
    {"key": "invertptt", "file": "usbradio.conf", "group": "usbradio", "kind": "boolean", "default": "no"},
    {"key": "rxondelay", "file": "usbradio.conf", "group": "usbradio", "kind": "number", "default": "0", "min": 0, "max": 1000},
    {"key": "txoffdelay", "file": "usbradio.conf", "group": "usbradio", "kind": "number", "default": "0", "min": 0, "max": 1000},
    {"key": "rxlpf", "file": "usbradio.conf", "group": "usbradio_filters", "kind": "choice", "default": "0",
     "choices": ("0", "1", "2"), "advanced": True},
    {"key": "rxhpf", "file": "usbradio.conf", "group": "usbradio_filters", "kind": "choice", "default": "0",
     "choices": ("0", "1"), "advanced": True},
    {"key": "txlpf", "file": "usbradio.conf", "group": "usbradio_filters", "kind": "choice", "default": "0",
     "choices": ("0", "1"), "advanced": True},
    {"key": "txhpf", "file": "usbradio.conf", "group": "usbradio_filters", "kind": "choice", "default": "0",
     "choices": ("0", "1", "2"), "advanced": True},
    {"key": "rxctcssrelax", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "choice", "default": "1",
     "choices": ("0", "1"), "advanced": True},
    {"key": "rxsqhyst", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "number", "default": "3000", "min": 0, "max": 999999, "advanced": True},
    {"key": "voxhangtime", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "number", "default": "2000", "min": 0, "max": 999999, "advanced": True},
    {"key": "txctcssdefault", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "text", "default": "100.0", "max": 40, "advanced": True},
    {"key": "rxctcssfreqs", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "text", "default": "100.0,91.5", "max": 200, "advanced": True},
    {"key": "txctcssfreqs", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "text", "default": "100.0,91.5", "max": 200, "advanced": True},
    {"key": "rxctcssoverride", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "boolean", "default": "no", "advanced": True},
    {"key": "rxsquelchdelay", "file": "usbradio.conf", "group": "usbradio_signal", "kind": "number", "default": "30", "min": 0, "max": 999999, "advanced": True},
    {"key": "duplex3", "file": "usbradio.conf", "group": "usbradio_advanced", "kind": "number", "default": "0", "min": 0, "max": 999, "advanced": True},
    {"key": "clipledgpio", "file": "usbradio.conf", "group": "usbradio_advanced", "kind": "number", "default": "0", "min": 0, "max": 999, "advanced": True},
    {"key": "legacyaudioscaling", "file": "usbradio.conf", "group": "usbradio_advanced", "kind": "boolean", "default": "no", "advanced": True},
    {"key": "eeprom", "file": "usbradio.conf", "group": "usbradio_advanced", "kind": "choice", "default": "0",
     "choices": ("0", "1"), "advanced": True},
    {"key": "hdwtype", "file": "usbradio.conf", "group": "usbradio_advanced", "kind": "choice", "default": "0",
     "choices": ("0", "1"), "advanced": True},
    {"key": "devstr", "file": "usbradio.conf", "group": "usbradio", "kind": "text", "default": "", "max": 200},
    {"key": "serial", "file": "usbradio.conf", "group": "usbradio", "kind": "text", "default": "", "max": 200},
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


def node_field_groups(node_number: int, settings: dict[str, str], locale: str = "en",
                      include_other_interfaces: bool = False,
                      defaults: dict[str, str] | None = None) -> list[dict]:
    """Build display-ready form groups from the stable field definitions."""
    catalog = _load_catalog(locale)
    english = _load_catalog("en")
    groups: list[dict] = []
    by_name: dict[tuple[str, bool, str | None], dict] = {}
    selected_channel = str(settings.get("rxchannel", "Local/pseudo"))
    selected_interface = selected_channel.split("/", 1)[0]
    for definition in _FIELD_DEFINITIONS:
        file_name = definition.get("file")
        interface = {"simpleusb.conf": "SimpleUSB", "usbradio.conf": "Radio"}.get(file_name)
        if interface and not include_other_interfaces and interface != selected_interface:
            continue
        group_key = definition["group"]
        advanced = key_in_advanced(definition)
        group_id = (group_key, advanced, interface)
        if group_id not in by_name:
            group = {"title": _message(f"group_{group_key}", locale, catalog, english), "fields": [],
                     "advanced": advanced, "interface": interface,
                     "active": interface is None or interface == selected_interface}
            by_name[group_id] = group
            groups.append(group)
        key = definition["key"]
        interface_prefix = {"SimpleUSB": "simpleusb", "Radio": "usbradio"}.get(interface)
        form_key = f"{interface_prefix}_{key}" if interface_prefix else key
        default = (defaults or {}).get(form_key, definition.get("default", ""))
        configured = settings.get(form_key, settings.get(key, default))
        value = str(default if configured is None else configured)
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
            choice_prefix = "usbradio_" if interface == "Radio" else ""
            choices = [(choice, _message(f"{choice_prefix}{key}_option_{choice}", locale, catalog, english))
                       for choice in definition["choices"]]
            if value not in {option[0] for option in choices}:
                choices.append((value, f"{value} ({_message('custom', locale, catalog, english)})"))
        else:
            choices = []
        message_prefix = "usbradio_" if interface == "Radio" else ""
        by_name[group_id]["fields"].append({
            **definition,
            "form_key": form_key,
            "label": _message(f"field_{message_prefix}{key}", locale, catalog, english),
            "help": _message(f"help_{message_prefix}{key}", locale, catalog, english),
            "value": value,
            "default_value": str(default),
            "required": definition.get("required", False),
            "has_default": form_key in (defaults or {}) or "default" in definition,
            "choices": choices,
            "advanced": advanced,
            "browser_max": max(definition.get("max", 0), existing_number) if existing_number is not None else definition.get("max"),
            "browser_min": min(definition.get("min", 0), existing_number) if existing_number is not None else definition.get("min"),
        })
    return groups


def key_in_advanced(definition: dict) -> bool:
    if definition.get("file") in {"simpleusb.conf", "usbradio.conf"}:
        return definition.get("advanced", False)
    return definition["key"] not in _BASIC_FIELDS


def node_fields_for_file(file_name: str) -> set[str]:
    return {field["key"] for field in _FIELD_DEFINITIONS
            if field.get("file", "rpt.conf") == file_name}


def usbradio_config_values(settings) -> dict[str, str]:
    """Return typed USBRadio fields as the strings written to usbradio.conf."""
    return interface_config_values(settings, "usbradio.conf")


def interface_config_values(settings, file_name: str,
                            defaults: dict[str, str] | None = None) -> dict[str, str]:
    """Return explicit interface overrides with declared defaults filled in."""
    definitions = {field["key"]: field for field in _FIELD_DEFINITIONS
                   if field.get("file") == file_name}
    result = {}
    for key in node_fields_for_file(file_name):
        definition = definitions[key]
        value = getattr(settings, key, None)
        if value is None:
            if "default" not in definition:
                continue
            result[key] = str((defaults or {}).get(key, definition["default"]))
            continue
        result[key] = ("yes" if value else "no") if definition["kind"] == "boolean" else str(value)
    return result


def apply_interface_config_values(settings, file_name: str, values: dict[str, str],
                                  defaults: dict[str, str] | None = None) -> None:
    """Set typed radio interface fields from validated Asterisk-style values."""
    definitions = {field["key"]: field for field in _FIELD_DEFINITIONS
                   if field.get("file") == file_name}
    for key, raw in values.items():
        definition = definitions.get(key)
        if definition is None:
            continue
        kind = definition["kind"]
        value = raw
        canonical = str(raw)
        if kind == "boolean":
            value = str(raw).lower() in {"yes", "true", "1", "on"}
            canonical = "yes" if value else "no"
        elif kind == "number" or kind == "choice" and str(raw).isdigit():
            value = int(raw)
            canonical = str(value)
        elif kind == "decimal":
            try:
                canonical = format(Decimal(str(raw)).normalize(), "f")
                value = canonical
            except InvalidOperation:
                canonical = str(raw)
        declared_default = (defaults or {}).get(key, definition.get("default"))
        if declared_default is not None and canonical == str(declared_default):
            setattr(settings, key, None)
            continue
        if declared_default is None and canonical == "":
            setattr(settings, key, None)
            continue
        setattr(settings, key, value)


def node_config_values(node, defaults: dict[str, str] | None = None) -> dict[str, str]:
    """Return typed node columns in their Asterisk configuration form."""
    result = {}
    for key, definition in NODE_CONFIG_FIELDS.items():
        value = getattr(node, key)
        if value is None:
            if "default" not in definition:
                continue
            result[key] = str((defaults or {}).get(key, definition["default"]))
            continue
        if definition["kind"] == "boolean":
            result[key] = "yes" if value else "no"
        else:
            result[key] = str(value)
    return result


def apply_node_config_values(node, values: dict[str, str],
                             defaults: dict[str, str] | None = None) -> None:
    """Set known node columns from Asterisk-style string values."""
    for key, value in values.items():
        definition = NODE_CONFIG_FIELDS.get(key)
        if definition is None:
            continue
        declared_default = (defaults or {}).get(key, definition.get("default"))
        canonical = str(value)
        if definition["kind"] == "boolean":
            value = str(value).lower() in {"yes", "true", "1", "on"}
            canonical = "yes" if value else "no"
        elif definition["kind"] == "number" or definition["kind"] == "choice" and key in {"duplex", "telemdefault", "parrot"}:
            value = int(value)
            canonical = str(value)
        if declared_default is not None and canonical == str(declared_default):
            setattr(node, key, None)
            continue
        if declared_default is None and canonical == "":
            setattr(node, key, None)
            continue
        setattr(node, key, value)


def validate_node_settings(form, node_number: int, existing: dict[str, str] | None = None) -> tuple[dict[str, str] | None, dict[str, str]]:
    """Validate named fields and return normalized Asterisk values by key."""
    values: dict[str, str] = {}
    errors: dict[str, str] = {}
    existing = existing or {}
    for definition in _FIELD_DEFINITIONS:
        key, kind = definition["key"], definition["kind"]
        interface = {"simpleusb.conf": "simpleusb", "usbradio.conf": "usbradio"}.get(
            definition.get("file"))
        form_key = f"{interface}_{key}" if interface else key
        previous = existing.get(form_key, existing.get(key))
        raw = form.get(form_key, form.get(key, ""))
        if form_key not in form and key not in form:
            previous_value = existing.get(form_key, existing.get(key, definition.get("default", "")))
            if previous_value is None:
                previous_value = definition.get("default", "")
            if definition.get("required", False) and not str(previous_value).strip():
                errors[form_key] = "This field is required."
                continue
            values[form_key] = previous_value
            continue
        if raw is None:
            raw = ""
        raw = str(raw)
        if raw == "" and definition.get("required", False):
            errors[form_key] = "This field is required."
            continue
        if kind == "channel":
            allowed = {"Local/pseudo", f"SimpleUSB/{node_number}", f"Radio/{node_number}",
                       f"Voter/{node_number}"}
            if raw not in allowed and raw != previous:
                errors[form_key] = "Choose a supported channel driver."
            else:
                values[form_key] = raw
        elif kind == "boolean":
            if raw not in {"yes", "no"}:
                errors[form_key] = "Choose yes or no."
            else:
                values[form_key] = raw
        elif kind == "choice":
            if raw not in definition["choices"] and raw != previous:
                errors[form_key] = "Choose one of the listed options."
            else:
                values[form_key] = raw
        elif kind == "number":
            if raw == previous:
                values[form_key] = raw
                continue
            try:
                number = int(raw)
                if not definition["min"] <= number <= definition["max"]:
                    raise ValueError
                values[form_key] = str(number)
            except (ValueError, TypeError):
                errors[form_key] = f"Enter a whole number from {definition['min']} to {definition['max']}."
        elif kind == "decimal":
            try:
                number = Decimal(raw)
                if (not number.is_finite()
                        or not Decimal(str(definition["min"])) <= number <= Decimal(str(definition["max"]))):
                    raise ValueError
                values[form_key] = format(number.normalize(), "f")
            except (InvalidOperation, ValueError, TypeError):
                errors[form_key] = f"Enter a number from {definition['min']} to {definition['max']}."
        else:
            value = raw.strip()
            if ("\n" in value or "\r" in value or len(value) > definition["max"]):
                errors[form_key] = f"Enter at most {definition['max']} characters on one line."
            else:
                values[form_key] = value
    return (None, errors) if errors else (values, {})


def _message(key: str, locale: str, catalog: dict, english: dict) -> str:
    return catalog.get(key, english.get(key, key))


def _load_catalog(locale: str) -> dict[str, str]:
    path = TRANSLATION_DIR / f"{locale}.json"
    if not path.is_file():
        path = TRANSLATION_DIR / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))
