"""Render a database revision into a fixed set of Asterisk configuration files."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, PackageLoader, StrictUndefined
from sqlalchemy import select

from .configuration import node_config_values, node_fields_for_file
from .database import session_factory
from .models import ConfigValue, CustomLine, Network, Node, Setting

GENERATED_FILES = ("rpt.conf", "iax.conf", "extensions.conf", "modules.conf",
                   "manager.conf", "echolink.conf", "usbradio.conf",
                   "simpleusb.conf", "voter.conf", "savenode.conf",
                   "rpt_http_registrations.conf")


def section_header(section: str) -> str:
    """Render a section name with Asterisk inheritance/template suffix syntax."""
    match = re.fullmatch(r"(.*?)(\([^()]*\))?", section)
    if match is None:
        return f"[{section}]"
    name, suffix = match.groups()
    return f"[{name}]{suffix or ''}"


def order_sections(sections: list[str]) -> list[str]:
    """Keep Asterisk template sections before sections that inherit from them."""
    unique = list(dict.fromkeys(section for section in sections if section))
    templates = {section[:-3]: section for section in unique if section.endswith("(!)")}
    parents: dict[str, str] = {}
    for section in unique:
        match = re.fullmatch(r"(.+)\(([^()]*)\)", section)
        if match and match.group(2) != "!" and match.group(2) in templates:
            parents[section] = templates[match.group(2)]

    ordered: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(section: str) -> None:
        if section in visited or section in visiting:
            return
        visiting.add(section)
        parent = parents.get(section)
        if parent is not None:
            visit(parent)
        visiting.remove(section)
        visited.add(section)
        ordered.append(section)

    for section in unique:
        visit(section)
    return ordered


def render_database(database: str | Path) -> dict[str, bytes]:
    templates = Environment(loader=PackageLoader("asterisk_node_manager", "conf"),
                            autoescape=False, undefined=StrictUndefined,
                            keep_trailing_newline=True)
    output: dict[str, bytes] = {}
    with session_factory(database)() as session:
        settings = {row.key: row.value for row in session.scalars(select(Setting))}
        default_key = settings.get("default_network_key", "")
        default_network = session.scalar(select(Network).where(Network.stable_key == default_key))
        advanced_networks = settings.get("advanced_node_networks", "false").lower() == "true"
        nodes = list(session.scalars(select(Node).order_by(Node.node_number)))
        simpleusb_fields = node_fields_for_file("simpleusb.conf")
        file_values = list(session.scalars(select(ConfigValue).order_by(
            ConfigValue.file_name, ConfigValue.section, ConfigValue.key)))
        custom_lines = list(session.scalars(select(CustomLine).order_by(
            CustomLine.file_name, CustomLine.id)))
        nodes_context = []
        usb_values = []
        for node in nodes:
            network = node.network if advanced_networks and node.network else default_network
            advanced = {value.key: value.value for value in file_values
                        if value.file_name == "rpt.conf" and value.section == str(node.node_number)
                        and value.key not in node_config_values(node)}
            rpt_settings = {**node_config_values(node), **advanced}
            nodes_context.append({
                "node_number": node.node_number, "name": node.name,
                "enabled": node.enabled,
                "settings": rpt_settings,
                "network_key": network.stable_key if network else None,
            })
            if node.simpleusb_settings:
                typed = node.simpleusb_settings
                for key in simpleusb_fields:
                    value = getattr(typed, key)
                    usb_values.append(SimpleNamespace(section=str(node.node_number), key=key,
                                                      value=("yes" if value else "no") if isinstance(value, bool)
                                                      else str(value), secret=False))
        for filename in GENERATED_FILES:
            values = [value for value in file_values if value.file_name == filename]
            custom = [line for line in custom_lines if line.file_name == filename]
            template_name = f"{filename}.j2"
            if filename == "rpt.conf":
                for node in nodes_context:
                    node["custom_lines"] = [line.content for line in custom
                                            if line.section == str(node["node_number"])]
                content = templates.get_template(template_name).render(
                    nodes=nodes_context,
                    values=[value for value in values if not value.section.isdigit()],
                    custom_lines=[line for line in custom if not line.section.isdigit()],
                    global_custom_lines=[line for line in custom if not line.section],
                    sections=order_sections([
                        *(line.section for line in custom if line.section and not line.section.isdigit()),
                        *(value.section for value in values if value.section and not value.section.isdigit()),
                    ]),
                    section_header=section_header)
            else:
                if filename == "simpleusb.conf":
                    values = [value for value in values
                              if not (value.section.isdigit() and value.key in simpleusb_fields)]
                    values.extend(usb_values)
                    values.sort(key=lambda value: (value.section, value.key))
                content = templates.get_template("generic.conf.j2").render(
                    filename=filename, values=values, custom_lines=custom,
                    sections=order_sections([
                        *(line.section for line in custom),
                        *(value.section for value in values),
                    ]),
                    section_header=section_header)
            output[filename] = content.encode("utf-8")
    return output


def hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


def describe(files: dict[str, bytes]) -> str:
    return json.dumps({name: len(content.splitlines()) for name, content in files.items()}, sort_keys=True)
