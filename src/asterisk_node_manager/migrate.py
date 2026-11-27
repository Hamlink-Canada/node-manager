"""Run packaged Alembic migrations against the configured SQLite database."""

from pathlib import Path
import sqlite3
import re

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from .database import create_database_engine, is_memory_database


def validate_database_backup(path: str | Path) -> bool:
    """Return whether a SQLite file is intact and carries known app migration metadata."""
    try:
        with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                return False
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if version is None:
                return False
        scripts = ScriptDirectory(str(Path(__file__).resolve().parent / "migrations"))
        return version[0] in {revision.revision for revision in scripts.walk_revisions()}
    except (sqlite3.Error, LookupError, TypeError):
        return False


def upgrade_database(database: str | Path) -> None:
    package_dir = Path(__file__).resolve().parent
    config = Config(str(package_dir / "alembic.ini"))
    config.set_main_option("script_location", str(package_dir / "migrations"))
    engine = create_database_engine(database)
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    _seed_configuration_defaults(database)
    if not is_memory_database(database):
        engine.dispose()


def _seed_configuration_defaults(database: str | Path) -> None:
    """Copy packaged baseline settings into the database as declared defaults."""
    from sqlalchemy import select
    from .asterisk_config import _split_inline_comment, parse_config
    from types import SimpleNamespace
    from .generate import GENERATED_FILES, _expand_asterisk_templates, section_header
    from .models import ConfigValue, CustomLine, ExtensionRule, ModuleDirective
    from .structured_config import parse_extension_rule, parse_module_directive
    from .database import session_factory

    base_dir = Path(__file__).resolve().parent / "conf" / "base"
    sessions = session_factory(database)
    with sessions.begin() as session:
        for filename in GENERATED_FILES:
            path = base_dir / f"{filename}.j2"
            if not path.is_file():
                continue
            values, preserved = parse_config(filename, path.read_text(encoding="utf-8"))
            value_rows = [SimpleNamespace(file_name=filename, section=section, key=key,
                                          value=value, secret=False)
                          for section, entries in values.items() for key, value in entries.items()]
            custom_rows = []
            for section, lines in preserved.items():
                for index, line in enumerate(lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith(";"):
                        continue
                    if stripped.startswith("#") and not stripped.lower().startswith("#include"):
                        continue
                    if stripped.lower().startswith('#tryinclude "custom/'):
                        continue
                    if "=" in line or "=>" in line:
                        line, _comment = _split_inline_comment(line)
                    if line.strip():
                        custom_rows.append(SimpleNamespace(section=section, line_number=index,
                                                           content=line))
            populated_sections = {row.section for row in value_rows} | {
                row.section for row in custom_rows if row.content.strip()}
            for section in set(values) | set(preserved):
                if section not in populated_sections:
                    custom_rows.append(SimpleNamespace(section=section, line_number=-1,
                                                       content=""))
            value_rows, custom_rows = _expand_asterisk_templates(value_rows, custom_rows)
            module_rows = []
            extension_rows = []
            remaining_custom_rows = []
            for line in custom_rows:
                if filename == "modules.conf":
                    directive = parse_module_directive(line.content)
                    if directive:
                        action, module = directive
                        module_rows.append((line.section, line.line_number, module, action))
                        continue
                if filename == "extensions.conf":
                    rule = parse_extension_rule(line.content)
                    if rule:
                        extension_rows.append((line.section, line.line_number, rule))
                        continue
                remaining_custom_rows.append(line)
            custom_rows = remaining_custom_rows
            for value in value_rows:
                    row = session.scalar(select(ConfigValue).where(
                        ConfigValue.file_name == filename, ConfigValue.section == value.section,
                        ConfigValue.key == value.key))
                    if row is None:
                        session.add(ConfigValue(file_name=filename, section=value.section, key=value.key,
                                                default_value=value.value, secret=value.secret))
                    else:
                        row.default_value = value.value
            already_seeded = session.scalar(select(CustomLine.id).where(
                CustomLine.file_name == filename, CustomLine.is_default.is_(True)).limit(1))
            if already_seeded is None:
                populated = {value.section for value in value_rows} | {line.section for line in custom_rows}
                source_sections = set(values) | set(preserved)
                template_names = {section[:-3] for section in source_sections
                                  if section.endswith("(!)")}
                consumed_templates = {
                    match.group(2) for section in source_sections
                    if (match := re.fullmatch(r"(.+)\(([^()]*)\)", section))
                    and match.group(2) in template_names
                }
                for section in source_sections:
                    if section.endswith("(!)") and section[:-3] in consumed_templates:
                        continue
                    concrete = section_header(section)[1:-1]
                    if concrete not in populated:
                        custom_rows.append(SimpleNamespace(section=concrete, line_number=-1,
                                                           content=""))
                for line in custom_rows:
                    session.add(CustomLine(file_name=filename, section=line.section,
                                           line_number=line.line_number, content=line.content,
                                           is_default=True))
            if filename == "modules.conf" and not session.scalar(select(ModuleDirective.id).where(
                    ModuleDirective.is_default.is_(True)).limit(1)):
                for section, line_number, module, action in module_rows:
                    session.add(ModuleDirective(section=section or "modules", line_number=line_number,
                                                module=module, action=action, is_default=True,
                                                is_custom=False, is_deleted=False))
            if filename == "extensions.conf" and not session.scalar(select(ExtensionRule.id).where(
                    ExtensionRule.is_default.is_(True)).limit(1)):
                for context, line_number, rule in extension_rows:
                    session.add(ExtensionRule(context=context, line_number=line_number,
                                              **rule, is_default=True, is_custom=False,
                                              is_deleted=False))
