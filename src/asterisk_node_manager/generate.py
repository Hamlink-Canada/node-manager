"""Render a database revision into a fixed set of Asterisk configuration files."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, PackageLoader, StrictUndefined
from sqlalchemy import func, select

from .configuration import (interface_config_values, node_config_values,
                            node_fields_for_file)
from .database import session_factory
from .models import (ConfigValue, CustomLine, CustomValue, ExtensionRule, ModuleDirective,
                     Network, Node, Setting)
from .networks import network_fields

GENERATED_FILES = ("rpt.conf", "iax.conf", "extensions.conf", "modules.conf",
                   "manager.conf", "echolink.conf", "usbradio.conf",
                   "simpleusb.conf", "voter.conf", "savenode.conf",
                   "rpt_http_registrations.conf")


def section_header(section: str) -> str:
    """Render a concrete section; Asterisk inheritance is expanded by this app."""
    plain_section = re.sub(r"\([^()]*\)$", "", section)
    return f"[{plain_section}]"


def _expand_asterisk_templates(values: list, custom: list) -> tuple[list, list]:
    """Materialize Asterisk section inheritance before rendering concrete sections."""
    all_sections = {item.section for item in [*values, *custom] if item.section}
    templates = {section[:-3]: section for section in all_sections if section.endswith("(!)")}
    children: dict[str, str] = {}
    for section in all_sections:
        match = re.fullmatch(r"(.+)\(([^()]*)\)", section)
        if match and match.group(2) in templates:
            children[section] = match.group(2)

    for source_section, parent_name in children.items():
        match = re.fullmatch(r"(.+)\(([^()]*)\)", source_section)
        if match is None:
            continue
        child_name = match.group(1)
        parent_section = templates[parent_name]
        for row in values:
            if row.section == source_section:
                row.section = child_name
        for row in custom:
            if row.section == source_section:
                row.section = child_name
        child_keys = {(row.section, row.key) for row in values if row.section == child_name}
        for row in values:
            if row.section == parent_section and (child_name, row.key) not in child_keys:
                values.append(SimpleNamespace(file_name=row.file_name, section=child_name,
                                              key=row.key, value=row.value, secret=row.secret))
        child_custom = [row for row in custom if row.section == child_name]
        parent_custom = [row for row in custom if row.section == parent_section]
        if parent_custom:
            offset = min((row.line_number for row in child_custom), default=0) - len(parent_custom)
            inherited = [SimpleNamespace(section=child_name, content=row.content,
                                         line_number=offset + index)
                         for index, row in enumerate(parent_custom)]
            custom.extend(inherited)

    consumed_templates = set(children.values())
    values = [row for row in values if not (
        row.section in {templates[name] for name in consumed_templates})]
    custom = [row for row in custom if not (
        row.section in {templates[name] for name in consumed_templates})]
    for row in values:
        row.section = re.sub(r"\([^()]*\)$", "", row.section)
    for row in custom:
        row.section = re.sub(r"\([^()]*\)$", "", row.section)
    return values, sorted(custom, key=lambda row: (row.section, row.line_number))


def order_sections(sections: list[str]) -> list[str]:
    """Preserve first-seen order after inheritance has been expanded."""
    return list(dict.fromkeys(section for section in sections if section))


def _network_registration(line: str, profiles: dict[int, dict]) -> tuple[str, str, str] | None:
    """Route a preserved numeric-node registration using that node's network profile."""
    match = re.match(r"^\s*register\s*(?:=>|=)\s*(\d+):([^@]+)@([^\s;]+)(.*)$", line, re.IGNORECASE)
    if match is None:
        return None
    node_number, password, old_server, suffix = match.groups()
    profile = profiles.get(int(node_number))
    if not profile:
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
        custom_values = list(session.scalars(select(CustomValue).order_by(
            CustomValue.file_name, CustomValue.section, CustomValue.key)))
        custom_lines = list(session.scalars(select(CustomLine).order_by(
            CustomLine.file_name, CustomLine.section, CustomLine.line_number, CustomLine.id)))
        custom_lines = [line for line in custom_lines if not line.is_deleted]
        module_directives = list(session.scalars(select(ModuleDirective).order_by(
            ModuleDirective.section, ModuleDirective.line_number, ModuleDirective.id)))
        extension_rules = list(session.scalars(select(ExtensionRule).order_by(
            ExtensionRule.context,
            func.coalesce(ExtensionRule.updated_line_number, ExtensionRule.line_number),
            ExtensionRule.id)))
        rpt_value_map = {}
        for value in file_values:
            if value.file_name == "rpt.conf":
                rpt_value_map[(value.section, value.key)] = SimpleNamespace(
                    file_name=value.file_name, section=value.section, key=value.key,
                    value=value.value, secret=value.secret)
        for value in custom_values:
            if value.file_name == "rpt.conf":
                rpt_value_map[(value.section, value.key)] = SimpleNamespace(
                    file_name=value.file_name, section=value.section, key=value.key,
                    value=value.value, secret=value.secret)
        rpt_values = list(rpt_value_map.values())
        rpt_custom_lines = [line for line in custom_lines if line.file_name == "rpt.conf"]
        rpt_node_defaults = {value.key: value.value for value in rpt_values
                             if value.section in {"node-main", "node-main(!)"}}
        effective_file_values = {(value.file_name, value.section, value.key): value
                                 for value in file_values}
        for value in custom_values:
            effective_file_values[(value.file_name, value.section, value.key)] = value
        interface_defaults = {
            filename: {value.key: value.value for value in effective_file_values.values()
                       if value.file_name == filename
                       and value.section in {"node-main", "node-main(!)"}}
            for filename in ("simpleusb.conf", "usbradio.conf")
        }
        rpt_values, rpt_custom_lines = _expand_asterisk_templates(rpt_values, rpt_custom_lines)
        node_defaults = {**rpt_node_defaults,
                         **{value.key: value.value for value in rpt_values
                            if value.section.startswith("node-main")}}
        simpleusb_defaults = interface_defaults["simpleusb.conf"]
        usbradio_defaults = interface_defaults["usbradio.conf"]
        nodes_context = []
        node_profiles = {}
        usb_values = []
        radio_values = []
        for node in nodes:
            network = node.network if advanced_networks and node.network else default_profile
            advanced = {value.key: value.value for value in rpt_values
                        if value.section == str(node.node_number)
                        and value.key not in node_config_values(node, node_defaults)}
            rpt_settings = {**node_defaults, **node_config_values(node, node_defaults), **advanced}
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
            rxchannel = rpt_settings["rxchannel"]
            if rxchannel.startswith("SimpleUSB/") and node.simpleusb_settings:
                typed = node.simpleusb_settings
                usb_values.extend(SimpleNamespace(section=f"{node.node_number}(node-main)", key=key,
                                                  value=value, secret=False)
                                  for key, value in interface_config_values(
                                      typed, "simpleusb.conf", simpleusb_defaults).items())
            if rxchannel.startswith("Radio/") and node.usbradio_settings:
                radio_values.extend(SimpleNamespace(section=f"{node.node_number}(node-main)", key=key,
                                                    value=value, secret=False)
                                    for key, value in interface_config_values(
                                        node.usbradio_settings, "usbradio.conf", usbradio_defaults).items())
        for filename in GENERATED_FILES:
            if filename == "rpt.conf":
                values, custom = rpt_values, rpt_custom_lines
            else:
                merged_values = {}
                for value in file_values:
                    if value.file_name == filename:
                        merged_values.setdefault(value.section, {})[value.key] = value.value
                for value in custom_values:
                    if value.file_name == filename:
                        merged_values.setdefault(value.section, {})[value.key] = value
                values = [SimpleNamespace(file_name=filename, section=section, key=key,
                                          value=value.value if hasattr(value, "value") else value,
                                          secret=getattr(value, "secret", False))
                          for section, entries in merged_values.items()
                          for key, value in entries.items()]
                custom = [line for line in custom_lines if line.file_name == filename]
                values, custom = _expand_asterisk_templates(values, custom)
            if filename == "modules.conf":
                active_module_actions = {
                    "chan_simpleusb.so": "load" if any(
                        node_config_values(node, node_defaults)["rxchannel"].startswith("SimpleUSB/")
                        for node in nodes) else "noload",
                    "chan_usbradio.so": "load" if any(
                        node_config_values(node, node_defaults)["rxchannel"].startswith("Radio/")
                        for node in nodes) else "noload",
                    "chan_voter.so": "load" if any(
                        node_config_values(node, node_defaults)["rxchannel"].startswith("Voter/")
                        for node in nodes) else "noload",
                    "chan_usrp.so": "load" if any(
                        node_config_values(node, node_defaults)["rxchannel"].startswith("USRP/")
                        for node in nodes) else "noload",
                    "res_usbradio.so": "require" if any(
                        node_config_values(node, node_defaults)["rxchannel"].startswith(
                            ("SimpleUSB/", "Radio/")) for node in nodes) else "noload",
                }
                for directive in module_directives:
                    if directive.is_deleted:
                        continue
                    module = directive.effective_module
                    action = active_module_actions.get(module, directive.effective_action)
                    custom.append(SimpleNamespace(
                        section=directive.section, line_number=directive.line_number,
                        content=f"{action} => {module}"))
                custom.sort(key=lambda line: (line.section, line.line_number))
            elif filename == "extensions.conf":
                for rule in extension_rules:
                    if rule.is_deleted:
                        continue
                    custom.append(SimpleNamespace(
                        section=rule.context,
                        line_number=(rule.updated_line_number
                                     if rule.updated_line_number is not None else rule.line_number),
                        content=rule.render()))
                custom.sort(key=lambda line: (line.section, line.line_number))
            base_sections = list(dict.fromkeys(
                [value.section for value in values if value.section and value.section != "node-main"]
                + [line.section for line in custom if line.section and line.section != "node-main"]))
            if filename in {"simpleusb.conf", "usbradio.conf"}:
                values = [SimpleNamespace(**{**vars(value), "section": f"{value.section}(node-main)"})
                          if value.section.isdigit() else value for value in values]
                custom = [SimpleNamespace(**{**vars(line), "section": f"{line.section}(node-main)"})
                          if line.section.isdigit() else line for line in custom]
            if filename in {"iax.conf", "rpt_http_registrations.conf"}:
                routed = []
                for line in custom_lines:
                    if not re.match(r"^\s*register\s*(?:=>|=)", line.content, re.IGNORECASE):
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
                node_sections = {str(node.node_number) for node in nodes}
                base_sections = [section for section in base_sections if section not in node_sections]
                for node in nodes_context:
                    node["custom_lines"] = [line.content for line in custom
                                            if line.section == str(node["node_number"])]
                content = templates.get_template(template_name).render(
                    nodes=nodes_context,
                    values=[value for value in values
                            if value.section not in node_sections and value.section != "node-main"],
                    custom_lines=[line for line in custom if line.section not in node_sections],
                    global_custom_lines=[line for line in custom if not line.section],
                    sections=order_sections([
                        *base_sections,
                        *(line.section for line in custom if line.section and line.section not in node_sections),
                        *(value.section for value in values if value.section and value.section != "node-main"
                          and value.section not in node_sections),
                    ]),
                    section_header=section_header)
            else:
                if filename == "simpleusb.conf":
                    configured_nodes = [node for node in nodes if node_config_values(node, node_defaults)["rxchannel"].startswith("SimpleUSB/")]
                    template_defaults = [value for value in values if value.section == "node-main"]
                    values = [value for value in values
                              if value.section != "node-main"
                              and not (_node_section(value.section) and value.key in simpleusb_fields)]
                    typed_by_node = {}
                    for value in usb_values:
                        typed_by_node.setdefault(value.section.split("(", 1)[0], {})[value.key] = value
                    for node in configured_nodes:
                        section = str(node.node_number)
                        node_values = {value.key: value for value in template_defaults}
                        node_values.update(typed_by_node.get(section, {}))
                        values.extend(SimpleNamespace(file_name=filename, section=section, key=key,
                                                      value=value.value, secret=value.secret)
                                      for key, value in node_values.items())
                    values.sort(key=lambda value: (value.section, value.key))
                elif filename == "usbradio.conf":
                    configured_nodes = [node for node in nodes if node_config_values(node, node_defaults)["rxchannel"].startswith("Radio/")]
                    template_defaults = [value for value in values if value.section == "node-main"]
                    values = [value for value in values
                              if value.section != "node-main"
                              and not (_node_section(value.section) and value.key in usbradio_fields)]
                    typed_by_node = {}
                    for value in radio_values:
                        typed_by_node.setdefault(value.section.split("(", 1)[0], {})[value.key] = value
                    for node in configured_nodes:
                        section = str(node.node_number)
                        node_values = {value.key: value for value in template_defaults}
                        node_values.update(typed_by_node.get(section, {}))
                        values.extend(SimpleNamespace(file_name=filename, section=section, key=key,
                                                      value=value.value, secret=value.secret)
                                      for key, value in node_values.items())
                    values.sort(key=lambda value: (value.section, value.key))
                content = templates.get_template(template_name).render(
                    filename=filename, values=values, custom_lines=custom,
                    sections=order_sections([
                        *base_sections,
                        *(line.section for line in custom),
                        *(value.section for value in values),
                    ]),
                    section_header=section_header)
            output[filename] = _without_comments(content).encode("utf-8")
    return output


def _without_comments(content: str) -> str:
    """Remove full-line and inline Asterisk comments from rendered output."""
    from .asterisk_config import _split_inline_comment

    lines = []
    for line in content.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(";") or (stripped.startswith("#") and not
                                         stripped.lower().startswith(("#include", "#tryinclude"))):
            continue
        if "=" in line or "=>" in line:
            line, _comment = _split_inline_comment(line)
        if line.strip():
            lines.append(line.rstrip())
    return "\n".join(lines) + ("\n" if lines else "")


def hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


def describe(files: dict[str, bytes]) -> str:
    return json.dumps({name: len(content.splitlines()) for name, content in files.items()}, sort_keys=True)
