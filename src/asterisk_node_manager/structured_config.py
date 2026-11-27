"""Parsing helpers for module directives and dialplan extension rules."""

from __future__ import annotations

import re

from .asterisk_config import _split_inline_comment
from .models import ExtensionRule, ModuleDirective


_MODULE_DIRECTIVE = re.compile(
    r"^\s*(load|noload|require)\s*(?:=>|=)\s*([^\s;]+)\s*$", re.IGNORECASE
)
_EXTENSION_DIRECTIVE = re.compile(r"^\s*(exten|same)\s*(?:=>|=)\s*(.*?)\s*$", re.IGNORECASE)
_APPLICATION = re.compile(r"^([A-Za-z0-9_.]+)(?:\((.*)\))?$", re.DOTALL)


def parse_module_directive(line: str) -> tuple[str, str] | None:
    """Return (action, module) for a module loading line, without comments."""
    uncommented, _comment = _split_inline_comment(line)
    match = _MODULE_DIRECTIVE.fullmatch(uncommented.strip())
    if not match:
        return None
    return match.group(1).lower(), match.group(2)


def parse_extension_rule(line: str) -> dict[str, str | None] | None:
    """Parse an exten/same rule while preserving application argument text."""
    uncommented, _comment = _split_inline_comment(line)
    match = _EXTENSION_DIRECTIVE.fullmatch(uncommented.strip())
    if not match:
        return None
    directive, payload = match.groups()
    directive = directive.lower()

    if directive == "exten":
        parts = payload.split(",", 2)
        if len(parts) != 3:
            return None
        extension, priority, application_expression = (part.strip() for part in parts)
    else:
        parts = payload.split(",", 1)
        if len(parts) != 2:
            return None
        extension = None
        priority, application_expression = (part.strip() for part in parts)

    application_match = _APPLICATION.fullmatch(application_expression)
    if application_match:
        application, arguments = application_match.groups()
    else:
        application, arguments = application_expression, None
    if not priority or not application:
        return None
    return {
        "directive": directive,
        "extension": extension,
        "priority": priority,
        "application": application,
        "arguments": arguments,
    }


def _format_extension_rule(rule: dict[str, str | None]) -> str:
    prefix = f"{rule['directive']} => "
    parts = ([rule["extension"]] if rule["directive"] == "exten" else [])
    parts.extend((rule["priority"], rule["application"]))
    payload = ",".join(parts)
    if rule["arguments"] is not None:
        payload += f"({rule['arguments']})"
    return prefix + payload


def save_structured_lines(db, filename: str, section_lines: dict[str, list[str]], *,
                          replace_defaults: bool) -> None:
    """Save module/extension directives, retaining built-ins behind overrides."""
    if filename == "modules.conf":
        _save_module_directives(db, section_lines, replace_defaults=replace_defaults)
    elif filename == "extensions.conf":
        _save_extension_rules(db, section_lines, replace_defaults=replace_defaults)


def _save_module_directives(db, section_lines: dict[str, list[str]], *, replace_defaults: bool) -> None:
    defaults = db.query(ModuleDirective).filter_by(is_default=True).all()
    custom_rows = db.query(ModuleDirective).filter_by(is_default=False).all()
    seen_default: set[int] = set()
    seen_custom: set[int] = set()
    for section, lines in section_lines.items():
        for line_number, line in enumerate(lines):
            parsed = parse_module_directive(line)
            if not parsed:
                continue
            action, module = parsed
            default = next((row for row in defaults if row.id not in seen_default
                            and row.section == (section or "modules") and row.module == module), None)
            if default is not None:
                seen_default.add(default.id)
                default.is_deleted = False
                if action == default.action and module == default.module:
                    default.revert_to_default()
                else:
                    default.is_custom = True
                    default.updated_action = action
                    default.updated_module = module if module != default.module else None
                continue
            custom = next((row for row in custom_rows if row.id not in seen_custom
                           and row.section == (section or "modules")
                           and row.effective_module == module), None)
            if custom is None:
                custom = ModuleDirective(section=section or "modules", line_number=line_number,
                                         module=module, action=action, is_default=False,
                                         is_custom=True, is_deleted=False)
                db.add(custom)
                custom_rows.append(custom)
            else:
                custom.is_deleted = False
                custom.is_custom = True
                custom.updated_action = action
                seen_custom.add(custom.id)
    if replace_defaults:
        for row in defaults:
            if row.id not in seen_default:
                row.is_deleted = True
    for row in custom_rows:
        if row.id not in seen_custom and row not in db.new:
            row.is_deleted = True


def _save_extension_rules(db, section_lines: dict[str, list[str]], *, replace_defaults: bool) -> None:
    existing = db.query(ExtensionRule).order_by(ExtensionRule.context,
                                                ExtensionRule.line_number,
                                                ExtensionRule.id).all()
    rows_by_context: dict[str, list[ExtensionRule]] = {}
    for row in existing:
        rows_by_context.setdefault(row.context, []).append(row)
    for context, lines in section_lines.items():
        parsed_rules = [rule for line in lines if (rule := parse_extension_rule(line))]
        context_rows = rows_by_context.get(context, [])
        seen_rows: set[int] = set()
        for index, rule in enumerate(parsed_rules):
            expected = _format_extension_rule(rule)
            row = next((candidate for candidate in context_rows
                        if id(candidate) not in seen_rows and candidate.render() == expected), None)
            if row is None:
                row = next((candidate for candidate in context_rows
                            if id(candidate) not in seen_rows), None)
            if row is None:
                row = ExtensionRule(context=context, line_number=index, **rule,
                                    is_default=False, is_custom=True, is_deleted=False)
                db.add(row)
                context_rows.append(row)
                rows_by_context[context] = context_rows
                seen_rows.add(id(row))
                continue
            seen_rows.add(id(row))
            row.is_deleted = False
            if row.is_default:
                current = (row.directive, row.extension, row.priority, row.application, row.arguments)
                desired = tuple(rule[key] for key in
                                ("directive", "extension", "priority", "application", "arguments"))
                if current == desired:
                    row.revert_to_default()
                else:
                    row.is_custom = True
                    (row.updated_directive, row.updated_extension, row.updated_priority,
                     row.updated_application, row.updated_arguments) = desired
            else:
                for key, value in rule.items():
                    setattr(row, key, value)
                row.is_custom = True
        for row in context_rows:
            if id(row) not in seen_rows and (replace_defaults or not row.is_default):
                row.is_deleted = True
    included = set(section_lines)
    for row in existing:
        if row.context not in included and (replace_defaults or not row.is_default):
            row.is_deleted = True
