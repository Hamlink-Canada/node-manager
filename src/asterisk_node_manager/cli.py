"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import grp
import pwd
import sqlite3
import tempfile
import sys
from pathlib import Path

from .config import load_settings
from .database import database_write_lock, session_factory, sqlite_snapshot
from .asterisk_config import is_secret_key, parse_config
from .migrate import upgrade_database, validate_database_backup
from .models import Change, ConfigValue, CustomLine, Network, Node, SimpleUSBSettings, USBRadioSettings
from .configuration import (NODE_CONFIG_FIELDS, apply_interface_config_values,
                            apply_node_config_values, node_config_values, node_fields_for_file)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="astnode", description="Manage Asterisk node configuration")
    parser.add_argument("--config", help="Path to TOML application configuration")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the database and apply migrations")
    commands.add_parser("status", help="Show database and configuration status")
    commands.add_parser("generate", help="Regenerate configured Asterisk files from SQLite")
    backup = commands.add_parser("backup", help="Copy the SQLite database to a path")
    backup.add_argument("path", type=Path)
    restore = commands.add_parser("restore", help="Restore SQLite database from a path")
    restore.add_argument("path", type=Path)
    importer = commands.add_parser("import", help="Preview or import existing Asterisk configuration")
    importer.add_argument("config_directory", type=Path)
    importer.add_argument("--commit", action="store_true", help="Commit the displayed import plan")
    writers = commands.add_parser("writers", help="Manage users who may change configuration through the web app")
    writers.add_argument("action", choices=("list", "add", "remove"))
    writers.add_argument("username", nargs="?")
    return parser


def main() -> int:
    args = _parser().parse_args()
    settings = load_settings(args.config)
    if settings.demo_mode:
        print("The in-memory demo database is available only through the web app.", file=sys.stderr)
        return 2
    if args.command == "init":
        _require_root()
        upgrade_database(settings.database)
        print(f"Initialized {settings.database}")
        return 0
    if args.command == "status":
        print(f"Database: {settings.database} ({'present' if settings.database.exists() else 'not initialized'})")
        if settings.database.exists():
            with session_factory(settings.database)() as session:
                print(f"Nodes: {session.query(Node).count()}")
                print(f"Networks: {session.query(Network).count()}")
        return 0
    if args.command == "generate":
        _require_root()
        from .generate import render_database
        from .writer import _replace_files
        _replace_files(settings.asterisk_directory, render_database(
            settings.database, network_profiles_enabled=settings.network_profiles_enabled,
            default_network=settings.default_network))
        print(f"Generated Asterisk configuration in {settings.asterisk_directory}")
        return 0
    if args.command == "backup":
        if not settings.database.is_file():
            print("Database is not initialized", file=sys.stderr)
            return 2
        args.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = sqlite_snapshot(settings.database, args.path.parent)
        os.replace(snapshot, args.path)
        print(f"Backup written to {args.path}")
        return 0
    if args.command == "restore":
        _require_root()
        if not args.path.is_file():
            print(f"Backup file not found: {args.path}", file=sys.stderr)
            return 2
        if not validate_database_backup(args.path):
            print(f"Not a valid Asterisk Node Manager backup: {args.path}", file=sys.stderr)
            return 2
        settings.database.parent.mkdir(parents=True, exist_ok=True)
        previous = sqlite_snapshot(settings.database) if settings.database.exists() else None
        fd, temp_name = tempfile.mkstemp(prefix=".node-manager-restore-", suffix=".sqlite3",
                                         dir=settings.database.parent)
        os.close(fd)
        restored = Path(temp_name)
        try:
            with sqlite3.connect(args.path) as source, sqlite3.connect(restored) as target:
                source.backup(target)
            if previous is not None:
                current_stat = settings.database.stat()
                try:
                    os.chown(restored, current_stat.st_uid, current_stat.st_gid)
                except PermissionError:
                    pass
                else:
                    os.chmod(restored, current_stat.st_mode & 0o777)
            else:
                try:
                    database_uid = pwd.getpwnam("asterisk-node-manager").pw_uid
                    database_gid = grp.getgrnam("asterisk-node-manager").gr_gid
                except KeyError:
                    os.chmod(restored, 0o640)
                else:
                    os.chown(restored, database_uid, database_gid)
                    os.chmod(restored, 0o640)
            os.replace(restored, settings.database)
            upgrade_database(settings.database)
            from .generate import render_database
            from .writer import _replace_files
            _replace_files(settings.asterisk_directory, render_database(
                settings.database, network_profiles_enabled=settings.network_profiles_enabled,
                default_network=settings.default_network))
        except Exception:
            if previous is not None and previous.exists():
                os.replace(previous, settings.database)
            else:
                settings.database.unlink(missing_ok=True)
            raise
        finally:
            if previous is not None:
                previous.unlink(missing_ok=True)
            restored.unlink(missing_ok=True)
        print(f"Database restored from {args.path} and configuration regenerated")
        return 0
    if args.command == "writers":
        if args.action == "list":
            try:
                print(settings.writer_allowlist.read_text(), end="")
            except FileNotFoundError:
                pass
            return 0
        _require_root()
        if not args.username or "\n" in args.username or ":" in args.username:
            print("Provide a single valid username", file=sys.stderr)
            return 2
        current = set()
        if settings.writer_allowlist.exists():
            current = {line.strip() for line in settings.writer_allowlist.read_text().splitlines()
                       if line.strip() and not line.lstrip().startswith("#")}
        if args.action == "add":
            current.add(args.username)
        else:
            current.discard(args.username)
        settings.writer_allowlist.parent.mkdir(parents=True, exist_ok=True)
        settings.writer_allowlist.write_text("".join(f"{user}\n" for user in sorted(current)))
        settings.writer_allowlist.chmod(0o640)
        os.chown(settings.writer_allowlist, 0, grp.getgrnam("asterisk-node-manager").gr_gid)
        print(f"Updated web writer allowlist: {settings.writer_allowlist}")
        return 0
    if args.command == "import":
        if args.commit:
            with database_write_lock(settings.database):
                return _import_config(args.config_directory, args.commit, settings)
        return _import_config(args.config_directory, args.commit, settings)
    return 2


def _require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("This command requires root or sudo")


def _import_config(path: Path, commit: bool, settings) -> int:
    if not path.is_dir():
        print(f"Configuration directory not found: {path}", file=sys.stderr)
        return 2
    files = sorted(item for item in path.glob("*.conf") if item.is_file())
    print(f"Import preview: {len(files)} configuration files found in {path}")
    recognized = 0
    preserved = 0
    for item in files:
        rows = parse_config(item.name, item.read_text(errors="replace"))
        recognized += sum(len(section) for section in rows[0].values())
        preserved += sum(len(lines) for lines in rows[1].values())
        print(f"  {item.name}: {sum(len(section) for section in rows[0].values())} settings, "
              f"{sum(len(lines) for lines in rows[1].values())} preserved lines")
    if not commit:
        print(f"Preview only: {recognized} settings and {preserved} unparsed lines.")
        print("Use --commit after reviewing the import plan.")
        return 0
    _require_root()
    upgrade_database(settings.database)
    with session_factory(settings.database)() as db:
        for item in files:
            values, lines = parse_config(item.name, item.read_text(errors="replace"))
            if item.name == "rpt.conf":
                for section, entries in values.items():
                    if section.isdigit():
                        node = db.query(Node).filter_by(node_number=int(section)).one_or_none()
                        if node is None:
                            node = Node(node_number=int(section), name=f"Node {section}")
                            db.add(node)
                        apply_node_config_values(node, entries)
                        for key, value in entries.items():
                            if key in NODE_CONFIG_FIELDS:
                                continue
                            _set_config_value(db, item.name, section, key, value)
                        continue
            if item.name == "simpleusb.conf":
                known_usb = node_fields_for_file("simpleusb.conf")
                for section, entries in values.items():
                    if section.isdigit():
                        node = db.query(Node).filter_by(node_number=int(section)).one_or_none()
                        if node is None:
                            node = Node(node_number=int(section), name=f"Node {section}")
                            db.add(node)
                        if node.simpleusb_settings is None:
                            node.simpleusb_settings = SimpleUSBSettings()
                        for key, value in entries.items():
                            if key not in known_usb:
                                _set_config_value(db, item.name, section, key, value)
                                continue
                            if key in {"rxboost", "deemphasis", "plfilter", "invertptt", "preemphasis"}:
                                value = value.lower() in {"yes", "true", "1", "on"}
                            elif key in {"rxondelay", "txoffdelay", "rxmixerset", "txmixaset", "txmixbset"}:
                                try:
                                    value = int(value)
                                except ValueError:
                                    continue
                            setattr(node.simpleusb_settings, key, value)
                        continue
            if item.name == "usbradio.conf":
                known_radio = node_fields_for_file("usbradio.conf")
                for section, entries in values.items():
                    if section.isdigit():
                        node = db.query(Node).filter_by(node_number=int(section)).one_or_none()
                        if node is None:
                            node = Node(node_number=int(section), name=f"Node {section}",
                                        rxchannel=f"Radio/{section}")
                            db.add(node)
                        elif node_config_values(node)["rxchannel"] == "Local/pseudo":
                            node.rxchannel = f"Radio/{section}"
                        if node.usbradio_settings is None:
                            node.usbradio_settings = USBRadioSettings()
                        apply_interface_config_values(node.usbradio_settings, "usbradio.conf", {
                            key: value for key, value in entries.items() if key in known_radio})
                        for key, value in entries.items():
                            if key not in known_radio:
                                _set_config_value(db, item.name, section, key, value)
                        continue
            for section, entries in values.items():
                if item.name in {"rpt.conf", "simpleusb.conf", "usbradio.conf"} and section.isdigit():
                    continue
                for key, value in entries.items():
                    _set_config_value(db, item.name, section, key, value)
            db.query(CustomLine).filter_by(file_name=item.name).delete()
            for section, entries in lines.items():
                for index, content in enumerate(entries):
                    db.add(CustomLine(file_name=item.name, section=section, line_number=index, content=content))
        revision = (db.query(Change.revision).order_by(Change.revision.desc()).first() or (0,))[0] + 1
        db.add(Change(actor=os.environ.get("SUDO_USER", os.environ.get("USER", "root")),
                      summary=f"Imported configuration from {path}", revision=revision,
                      details={"record": "configuration_import",
                               "files": [item.name for item in files]}))
        db.commit()
    from .writer import _replace_files
    from .generate import render_database
    _replace_files(settings.asterisk_directory, render_database(
        settings.database, network_profiles_enabled=settings.network_profiles_enabled,
        default_network=settings.default_network))
    print(f"Imported {len(files)} files and regenerated Asterisk configuration.")
    return 0


def _set_config_value(db, filename: str, section: str, key: str, value: str) -> None:
    old = db.query(ConfigValue).filter_by(file_name=filename, section=section, key=key).one_or_none()
    if old is None:
        db.add(ConfigValue(file_name=filename, section=section, key=key, value=value,
                           secret=is_secret_key(key)))
    else:
        old.value = value
        old.secret = is_secret_key(key)


if __name__ == "__main__":
    raise SystemExit(main())
