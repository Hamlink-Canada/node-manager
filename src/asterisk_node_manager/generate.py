"""Render a database revision into a fixed set of Asterisk configuration files."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, PackageLoader, StrictUndefined
from sqlalchemy import select

from .configuration import node_config_values, node_fields_for_file, usbradio_config_values
from .database import session_factory
from .models import ConfigValue, CustomLine, Network, Node, Setting
from .networks import network_fields

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


def _network_registration(line: str, profiles: dict[int, dict]) -> tuple[str, str, str] | None:
    """Route a preserved numeric-node registration using that node's network profile."""
    match = re.match(r"^\s*register\s*=>\s*(\d+):([^@]+)@([^\s;]+)(.*)$", line, re.IGNORECASE)
    if match is None:
        return None
    node_number, password, old_server, suffix = match.groups()
    profile = profiles.get(int(node_number))
    if profile is None:
        return None
    method = profile.get("registration_method", "none")
    if method == "none":
        return ("", "", "")
    if method == "http":
        server = profile.get("http_registration_server") or old_server
        return "rpt_http_registrations.conf", "registrations", \
            f"register => {node_number}:{password}@{server}{suffix}"
    if method == "iax":
        server = profile.get("iax_registration_server") or old_server
        port = profile.get("iax_registration_port", 4569)
        server = re.sub(r":\d+$", "", server)
        server = f"{server}:{port}"
        return "iax.conf", "general", f"register => {node_number}:{password}@{server}{suffix}"
    return None


def _base_configuration(filename: str):
    """Load the packaged baseline as configuration data for one generated file."""
    from .asterisk_config import parse_config

    path = Path(__file__).parent / "conf" / "base" / filename
    if not path.is_file():
        return {}, {}
    return parse_config(filename, path.read_text(encoding="utf-8"))


def _node_section(section: str) -> bool:
    return re.fullmatch(r"\d+(?:\([^()]*\))?", section) is not None


def render_database(database: str | Path, *, network_profiles_enabled: bool = False,
                    default_network: str = "allstarlink") -> dict[str, bytes]:
    templates = Environment(loader=PackageLoader("asterisk_node_manager", "conf"),
                            autoescape=False, undefined=StrictUndefined,
                            keep_trailing_newline=True)
    output: dict[str, bytes] = {}
    with session_factory(database)() as session:
        settings = {row.key: row.value for row in session.scalars(select(Setting))}
        advanced_networks = (network_profiles_enabled
                             and settings.get("advanced_node_networks", "false").lower() == "true")
        default_key = (settings.get("default_network_key") or default_network
                       if advanced_networks else default_network)
        default_profile = session.scalar(select(Network).where(Network.stable_key == default_key))
        nodes = list(session.scalars(select(Node).order_by(Node.node_number)))
        simpleusb_fields = node_fields_for_file("simpleusb.conf")
        usbradio_fields = node_fields_for_file("usbradio.conf")
        file_values = list(session.scalars(select(ConfigValue).order_by(
            ConfigValue.file_name, ConfigValue.section, ConfigValue.key)))
        custom_lines = list(session.scalars(select(CustomLine).order_by(
            CustomLine.file_name, CustomLine.id)))
        nodes_context = []
        node_profiles = {}
        usb_values = []
        radio_values = []
        for node in nodes:
            network = node.network if advanced_networks and node.network else default_profile
            advanced = {value.key: value.value for value in file_values
                        if value.file_name == "rpt.conf" and value.section == str(node.node_number)
                        and value.key not in node_config_values(node)}
            rpt_settings = {**node_config_values(node), **advanced}
            profile = network_fields(network) if network else {}
            node_profiles[node.node_number] = profile
            if profile:
                # A selected profile controls status reporting even when it disables it.
                rpt_settings.pop("statpost_url", None)
                rpt_settings.pop("statpost_time", None)
                rpt_settings["node_lookup_method"] = profile["node_lookup_method"]
                if profile["dns_node_domain"]:
                    rpt_settings["dns_node_domain"] = profile["dns_node_domain"]
                if profile["node_lookup_method"] != "file":
                    rpt_settings["max_dns_node_length"] = str(profile["max_dns_node_length"])
                if profile["node_lookup_method"] in {"file", "both"} and profile["external_node_file"]:
                    rpt_settings["extnodefile"] = profile["external_node_file"]
                if profile["stats_enabled"] and profile["stats_post_url"]:
                    rpt_settings["statpost_url"] = profile["stats_post_url"]
                    rpt_settings["statpost_time"] = str(profile["stats_post_interval"])
            nodes_context.append({
                "node_number": node.node_number, "name": node.name,
                "enabled": node.enabled,
                "settings": rpt_settings,
                "network_key": network.stable_key if network else None,
            })
            if node.rxchannel.startswith("SimpleUSB/") and node.simpleusb_settings:
                typed = node.simpleusb_settings
                for key in simpleusb_fields:
                    value = getattr(typed, key)
                    usb_values.append(SimpleNamespace(section=f"{node.node_number}(node-main)", key=key,
                                                      value=("yes" if value else "no") if isinstance(value, bool)
                                                      else str(value), secret=False))
            if node.rxchannel.startswith("Radio/") and node.usbradio_settings:
                radio_values.extend(SimpleNamespace(section=f"{node.node_number}(node-main)", key=key, value=value,
                                                     secret=False)
                                    for key, value in usbradio_config_values(node.usbradio_settings).items())
        for filename in GENERATED_FILES:
            base_values, base_custom = _base_configuration(filename)
            base_sections = list(dict.fromkeys((*base_values, *base_custom)))
            merged_values = {section: dict(entries) for section, entries in base_values.items()}
            for value in file_values:
                if value.file_name == filename:
                    merged_values.setdefault(value.section, {})[value.key] = value
            values = [SimpleNamespace(file_name=filename, section=section, key=key,
                                      value=value.value if hasattr(value, "value") else value,
                                      secret=getattr(value, "secret", False))
                      for section, entries in merged_values.items()
                      for key, value in entries.items()]
            custom = [SimpleNamespace(section=section, line_number=index, content=content)
                      for section, lines in base_custom.items()
                      for index, content in enumerate(lines)]
            custom.extend(line for line in custom_lines if line.file_name == filename)
            if filename in {"simpleusb.conf", "usbradio.conf"}:
                values = [SimpleNamespace(**{**vars(value), "section": f"{value.section}(node-main)"})
                          if value.section.isdigit() else value for value in values]
                custom = [SimpleNamespace(**{**vars(line), "section": f"{line.section}(node-main)"})
                          if line.section.isdigit() else line for line in custom]
            if filename in {"iax.conf", "rpt_http_registrations.conf"}:
                routed = []
                for line in custom_lines:
                    if not re.match(r"^\s*register\s*=>", line.content, re.IGNORECASE):
                        continue
                    destination = _network_registration(line.content, node_profiles)
                    if destination is not None:
                        routed.append((line, destination))
                custom = [line for line in custom if not any(line is source for source, _ in routed)]
                for source, destination in routed:
                    target_file, section, content = destination
                    if target_file == filename and content:
                        custom.append(SimpleNamespace(section=section, content=content,
                                                      line_number=source.line_number))
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
                        *base_sections,
                        *(line.section for line in custom if line.section and not _node_section(line.section)),
                        *(value.section for value in values if value.section and not _node_section(value.section)),
                    ]),
                    section_header=section_header)
            else:
                if filename == "simpleusb.conf":
                    values = [value for value in values
                              if not (_node_section(value.section) and value.key in simpleusb_fields)]
                    values.extend(usb_values)
                    values.sort(key=lambda value: (value.section, value.key))
                elif filename == "usbradio.conf":
                    values = [value for value in values
                              if not (_node_section(value.section) and value.key in usbradio_fields)]
                    values.extend(radio_values)
                    values.sort(key=lambda value: (value.section, value.key))
                elif filename == "modules.conf":
                    active_drivers = {
                        "chan_simpleusb.so": any(node.rxchannel.startswith("SimpleUSB/") for node in nodes),
                        "chan_usbradio.so": any(node.rxchannel.startswith("Radio/") for node in nodes),
                        "chan_voter.so": any(node.rxchannel.startswith("Voter/") for node in nodes),
                    }
                    rewritten = []
                    for line in custom:
                        match = re.match(r"^(\s*)(load|noload)(\s*(?:=>|=)\s*)([^\s;]+)(.*)$",
                                         line.content, re.IGNORECASE)
                        if match and match.group(4) in active_drivers:
                            indent, _, separator, module, suffix = match.groups()
                            directive = "load" if active_drivers[module] else "noload"
                            line = SimpleNamespace(section=line.section, line_number=line.line_number,
                                                   content=f"{indent}{directive}{separator}{module}{suffix}")
                        rewritten.append(line)
                    custom = rewritten
                content = templates.get_template("generic.conf.j2").render(
                    filename=filename, values=values, custom_lines=custom,
                    sections=order_sections([
                        *base_sections,
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
