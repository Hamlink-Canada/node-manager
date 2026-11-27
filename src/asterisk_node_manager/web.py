"""Flask management interface."""

from __future__ import annotations

import os
import re
import json
import difflib
import logging
import socket
import tempfile
import threading
import hashlib
import sqlite3
from urllib.parse import urlsplit
from functools import wraps
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from flask_bootstrap import Bootstrap5
from sqlalchemy import func, select
from waitress import serve

from .config import Settings, load_settings
from .database import (acquire_database_write_lock, database_exists, database_write_lock,
                       dispose_database_engine,
                       is_memory_database, release_database_write_lock, restore_sqlite_snapshot,
                       session_factory, sqlite_snapshot)
from .asterisk_config import SECRET_VALUE, is_secret_key, parse_config
from .generate import GENERATED_FILES, render_database
from .models import Change, ConfigValue, CustomLine, Network, Node, Setting, SimpleUSBSettings, USBRadioSettings
from .migrate import upgrade_database
from .demo import DEMO_USERNAME, initialize_demo
from .networks import (NETWORK_DEFAULTS, NETWORK_FIELD_DEFINITIONS, load_network_profiles,
                       network_fields, parse_network_profile)
from . import __version__
from .configuration import (
    NODE_CONFIG_FIELDS,
    apply_interface_config_values,
    apply_node_config_values,
    available_locales,
    node_field_groups,
    node_config_values,
    node_fields_for_file,
    translate,
    validate_node_settings,
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    if settings.demo_mode:
        if not is_memory_database(settings.database):
            raise ValueError("Demo mode requires an in-memory database")
        initialize_demo(settings.database)
    if database_exists(settings.database):
        with database_write_lock(settings.database):
            loaded_profiles = load_network_profiles(
                settings.network_profiles_directory, settings.database)
        if loaded_profiles:
            logger.info("Loaded %d network profile files from %s", loaded_profiles,
                        settings.network_profiles_directory)
    if settings.demo_mode:
        _request_generation(settings)
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.config["BOOTSTRAP_SERVE_LOCAL"] = True
    Bootstrap5(app)
    app.secret_key = _read_secret(settings.secret_key_file, demo_mode=settings.demo_mode)
    app.config["MAX_CONTENT_LENGTH"] = 104_857_600
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    def request_locale() -> str:
        return request.accept_languages.best_match(available_locales()) or "en"

    app.jinja_env.globals["_"] = lambda key: translate(request_locale(), key)
    sessions = session_factory(settings.database)
    write_lock = threading.RLock()

    @app.before_request
    def protect_mutations_and_serialize_writes():
        is_mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if is_mutation:
            origin = request.headers.get("Origin")
            referer = request.headers.get("Referer")
            source = origin or referer
            if not source and not app.testing:
                abort(400, "A same-origin request is required")
            if source:
                parsed = urlsplit(source)
                if parsed.netloc != request.host or parsed.scheme != request.scheme:
                    abort(400, "Cross-origin requests are not allowed")
        if is_mutation or is_memory_database(settings.database):
            write_lock.acquire()
            request.environ["node_manager_write_lock"] = True
            if is_mutation and current_user() in writers():
                request.environ["node_manager_database_lock"] = acquire_database_write_lock(
                    settings.database)
            if is_mutation and current_user() in writers():
                existed = is_memory_database(settings.database) or Path(settings.database).is_file()
                request.environ["node_manager_prewrite_database"] = (
                    _sqlite_snapshot(settings.database) if existed else None, existed)

    @app.teardown_request
    def release_write_lock(_error=None):
        lock_fd = request.environ.pop("node_manager_database_lock", None)
        if lock_fd is not None:
            release_database_write_lock(lock_fd)
        if request.environ.pop("node_manager_write_lock", False):
            write_lock.release()

    @app.after_request
    def recover_failed_write(response):
        state = request.environ.pop("node_manager_prewrite_database", None)
        if state is None:
            return response
        snapshot, existed = state
        try:
            if response.status_code >= 500:
                dispose_database_engine(settings.database)
                if existed and snapshot is not None:
                    if not is_memory_database(settings.database):
                        current = Path(settings.database).stat() if Path(settings.database).exists() else None
                        if current is not None:
                            os.chmod(snapshot, current.st_mode & 0o777)
                            try:
                                os.chown(snapshot, current.st_uid, current.st_gid)
                            except PermissionError:
                                pass
                    restore_sqlite_snapshot(settings.database, snapshot)
                else:
                    if not is_memory_database(settings.database):
                        Path(settings.database).unlink(missing_ok=True)
                dispose_database_engine(settings.database)
                try:
                    _request_generation(settings)
                except Exception:
                    app.logger.exception("Failed to restore generated files after a rolled-back request")
        finally:
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
        return response

    def current_user() -> str | None:
        return session.get("username")

    def writers() -> set[str]:
        if settings.demo_mode:
            return {DEMO_USERNAME}
        try:
            return {line.strip() for line in settings.writer_allowlist.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")}
        except OSError:
            return set()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user():
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def write_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user() not in writers():
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def require_network_profiles() -> None:
        if not settings.network_profiles_enabled:
            abort(404)

    app.jinja_env.globals["is_writer"] = lambda: current_user() in writers()

    @app.context_processor
    def add_network_context():
        return {"network_profiles_enabled": settings.network_profiles_enabled}

    @app.context_processor
    def add_demo_context():
        return {"demo_mode": settings.demo_mode, "demo_username": DEMO_USERNAME}

    @app.get("/login")
    def login():
        return render_template("login.html", error=None)

    @app.post("/login")
    def login_post():
        next_url = _safe_local_redirect(request.args.get("next"))
        if settings.demo_mode:
            session.clear()
            session["username"] = DEMO_USERNAME
            return redirect(next_url or url_for("index"))
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not username or not password or not _request_authentication(settings, username, password):
            return render_template("login.html", error="Login failed"), 401
        session.clear()
        session["username"] = username
        return redirect(next_url or url_for("index"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index():
        with sessions() as db:
            node_count = db.query(func.count(Node.id)).scalar()
            networks = db.query(Network).order_by(Network.name).all()
            nodes = db.query(Node).order_by(Node.node_number).all()
            node_network_names = {node.id: (node.network.name if node.network else "Default network")
                                  for node in nodes}
            values = {row.key: row.value for row in db.scalars(select(Setting))}
            changes = db.scalars(select(Change).order_by(Change.revision.desc()).limit(20)).all()
        return render_template("index.html", node_count=node_count, networks=networks,
                               nodes=nodes, username=current_user(),
                               node_network_names=node_network_names,
                               default_network=(values.get("default_network_key") or settings.default_network
                                                if settings.network_profiles_enabled
                                                and values.get("advanced_node_networks") == "true"
                                                else settings.default_network),
                               advanced_networks=(settings.network_profiles_enabled
                                                  and values.get("advanced_node_networks") == "true"),
                               network_profiles_enabled=settings.network_profiles_enabled,
                               changes=changes)

    @app.get("/settings")
    @write_required
    def settings_page():
        with sessions() as db:
            values = {row.key: row.value for row in db.scalars(select(Setting))}
        return render_template("settings.html",
                               network_profiles_enabled=settings.network_profiles_enabled,
                               advanced_networks=(settings.network_profiles_enabled
                                                  and values.get("advanced_node_networks") == "true"),
                               default_network=settings.default_network)

    @app.get("/networks")
    @login_required
    def networks_page():
        require_network_profiles()
        with sessions() as db:
            networks = db.scalars(select(Network).order_by(Network.name)).all()
            values = {row.key: row.value for row in db.scalars(select(Setting))}
        return render_template("networks.html", networks=networks,
                               default_network=(values.get("default_network_key") or settings.default_network
                                                if values.get("advanced_node_networks") == "true"
                                                else settings.default_network),
                               advanced_networks=(values.get("advanced_node_networks") == "true"))

    @app.get("/networks/add")
    @write_required
    def add_network_page():
        require_network_profiles()
        return render_template("network-form.html", source="manual",
                               fields=NETWORK_FIELD_DEFINITIONS,
                               values=NETWORK_DEFAULTS, errors={})

    @app.get("/networks/import")
    @write_required
    def import_network_page():
        require_network_profiles()
        return render_template("network-import.html")

    @app.get("/backup-restore")
    @write_required
    def backup_restore_page():
        return render_template("backup-restore.html")

    @app.route("/nodes/setup", methods=["GET", "POST"])
    @write_required
    def node_setup():
        values = {
            "node_number": request.form.get("node_number", ""),
            "name": request.form.get("name", ""),
            "callsign": request.form.get("callsign", "").strip().upper(),
            "profile": request.form.get("profile", "simplex_hotspot"),
            "interface": request.form.get("interface", "SimpleUSB"),
        }
        errors = {}
        if request.method == "POST":
            try:
                node_number = int(values["node_number"])
                if not 1 <= node_number <= 2**63 - 1:
                    raise ValueError
            except ValueError:
                errors["node_number"] = "Enter a positive whole number."
                node_number = None
            name = values["name"].strip()
            if not name or len(name) > 200 or any(char in name for char in "\r\n"):
                errors["name"] = "Enter a name of at most 200 characters on one line."
            if not re.fullmatch(r"[A-Z0-9/-]{1,16}", values["callsign"]):
                errors["callsign"] = "Enter a call sign using up to 16 letters, numbers, / or -."
            profiles = {
                "simplex_no_telemetry": 0,
                "simplex_hotspot": 1,
                "full_duplex_repeater": 2,
                "hub_no_radio": 0,
            }
            if values["profile"] not in profiles:
                errors["profile"] = "Choose one of the listed node setups."
            if values["profile"] != "hub_no_radio" and values["interface"] not in {
                    "SimpleUSB", "Radio", "Voter"}:
                errors["interface"] = "Choose one of the listed radio interfaces."
            if not errors:
                with sessions() as db:
                    if db.scalar(select(Node.id).where(Node.node_number == node_number)) is not None:
                        errors["node_number"] = "That Node ID is already configured."
            if not errors:
                duplex = profiles[values["profile"]]
                channel = ("Local/pseudo" if values["profile"] == "hub_no_radio"
                           else f"{values['interface']}/{node_number}")
                with sessions.begin() as db:
                    node = Node(node_number=node_number, name=name)
                    apply_node_config_values(node, {
                        "rxchannel": channel,
                        "duplex": str(duplex),
                        "idrecording": f"|i{values['callsign']}",
                    })
                    db.add(node)
                    if values["interface"] == "SimpleUSB" and values["profile"] != "hub_no_radio":
                        db.add(SimpleUSBSettings(node=node))
                    if values["interface"] == "Radio" and values["profile"] != "hub_no_radio":
                        db.add(USBRadioSettings(node=node))
                    _record_change(db, current_user() or "", f"Set up node {node_number}", {
                        "record": "node_setup",
                        "node_number": node_number,
                        "profile": values["profile"],
                        "interface": values["interface"] if values["profile"] != "hub_no_radio" else None,
                    })
                dispose_database_engine(settings.database)
                _regenerate_or_503(settings)
                return redirect(url_for("index"))
        return render_template("node-setup.html", values=values, errors=errors,
                               initial_step=1 if set(errors) & {"profile", "interface"} else 0)

    @app.post("/nodes")
    @write_required
    def create_node():
        try:
            node_number = int(request.form.get("node_number", ""))
        except ValueError:
            abort(400, "Node Number must be an integer")
        name = request.form.get("name", "").strip()
        if not 1 <= node_number <= 2**63 - 1 or not name or len(name) > 200:
            abort(400, "Provide a positive Node Number and a name")
        with sessions() as db:
            if db.scalar(select(Node.id).where(Node.node_number == node_number)) is not None:
                abort(409, "That Node Number is already configured")
        with sessions.begin() as db:
            db.add(Node(node_number=node_number, name=name))
            _record_change(db, current_user() or "", f"Added node {node_number}",
                           {"record": "node", "node_number": node_number, "operation": "create"})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.route("/nodes/<int:node_id>/configuration", methods=["GET", "POST"])
    @login_required
    def node_configuration(node_id: int):
        with sessions() as db:
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            node_number, name = node.node_number, node.name
            existing = node_config_values(node)
            for value in db.scalars(select(ConfigValue).where(
                    ConfigValue.file_name == "rpt.conf",
                    ConfigValue.section == str(node_number))).all():
                if value.key not in NODE_CONFIG_FIELDS:
                    existing[value.key] = value.value
            if node.simpleusb_settings:
                for key in node_fields_for_file("simpleusb.conf"):
                    value = getattr(node.simpleusb_settings, key)
                    existing[f"simpleusb_{key}"] = ("yes" if value else "no") if isinstance(value, bool) else str(value)
            simpleusb_values = db.scalars(select(ConfigValue).where(
                ConfigValue.file_name == "simpleusb.conf",
                ConfigValue.section == str(node_number))).all()
            existing.update({f"simpleusb_{value.key}": value.value for value in simpleusb_values})
            if node.usbradio_settings:
                for key in node_fields_for_file("usbradio.conf"):
                    value = getattr(node.usbradio_settings, key)
                    existing[f"usbradio_{key}"] = ("yes" if value else "no") if isinstance(value, bool) else str(value)
            usbradio_values = db.scalars(select(ConfigValue).where(
                ConfigValue.file_name == "usbradio.conf",
                ConfigValue.section == str(node_number))).all()
            existing.update({f"usbradio_{value.key}": value.value for value in usbradio_values})
        if request.method == "GET":
            groups = node_field_groups(node_number, existing, request_locale(), include_other_interfaces=True)
            return render_template("node-configuration.html", node_id=node_id,
                                   node_number=node_number, node_name=name,
                                   groups=[group for group in groups if not group["advanced"]],
                                   advanced_groups=[group for group in groups if group["advanced"]],
                                   advanced_view=False, can_write=current_user() in writers(), errors={})
        if current_user() not in writers():
            abort(403)
        values, errors = validate_node_settings(request.form, node_number, existing)
        if errors:
            groups = node_field_groups(node_number, request.form, request_locale(), include_other_interfaces=True)
            return render_template("node-configuration.html", node_id=node_id,
                                   node_number=node_number, node_name=name,
                                   groups=[group for group in groups if not group["advanced"]],
                                   advanced_groups=[group for group in groups if group["advanced"]],
                                   advanced_view=request.form.get("advanced_view") == "yes",
                                   can_write=True, errors=errors), 400
        with sessions.begin() as db:
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            apply_node_config_values(node, {key: value for key, value in values.items()
                                            if key in NODE_CONFIG_FIELDS})
            simpleusb_fields = node_fields_for_file("simpleusb.conf")
            usbradio_fields = node_fields_for_file("usbradio.conf")
            usb = node.simpleusb_settings
            if values["rxchannel"].startswith("SimpleUSB/") or usb is not None:
                if usb is None:
                    usb = SimpleUSBSettings(node=node)
                    db.add(usb)
                apply_interface_config_values(usb, "simpleusb.conf", {
                    key: values[f"simpleusb_{key}"] for key in simpleusb_fields})
            radio = node.usbradio_settings
            if values["rxchannel"].startswith("Radio/") or radio is not None:
                if radio is None:
                    radio = USBRadioSettings(node=node)
                    db.add(radio)
                apply_interface_config_values(radio, "usbradio.conf", {
                    key: values[f"usbradio_{key}"] for key in usbradio_fields})
            for key, value in values.items():
                if key in NODE_CONFIG_FIELDS or key.startswith(("simpleusb_", "usbradio_")):
                    continue
                row = db.scalar(select(ConfigValue).where(
                    ConfigValue.file_name == "rpt.conf", ConfigValue.section == str(node.node_number),
                    ConfigValue.key == key))
                if row is None:
                    db.add(ConfigValue(file_name="rpt.conf", section=str(node.node_number),
                                       key=key, value=value, secret=False))
                else:
                    row.value = value
            _record_change(db, current_user() or "", f"Updated configuration for node {node.node_number}",
                           {"record": "node_configuration", "node_number": node.node_number,
                            "keys": sorted(values)})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("node_configuration", node_id=node_id))

    @app.post("/nodes/<int:node_id>/delete")
    @write_required
    def delete_node(node_id: int):
        with sessions.begin() as db:
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            db.delete(node)
            node_number = node.node_number
            for file_name in GENERATED_FILES:
                db.query(ConfigValue).filter_by(file_name=file_name, section=str(node_number)).delete()
                db.query(CustomLine).filter_by(file_name=file_name, section=str(node_number)).delete()
            _record_change(db, current_user() or "", f"Removed node {node_number}",
                           {"record": "node", "node_number": node_number, "operation": "delete"})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/nodes/<int:node_id>/network")
    @write_required
    def assign_network(node_id: int):
        require_network_profiles()
        with sessions.begin() as db:
            multi_network = db.get(Setting, "advanced_node_networks")
            if multi_network is None or multi_network.value != "true":
                abort(404)
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            raw_id = request.form.get("network_id", "")
            if raw_id:
                try:
                    network_id = int(raw_id)
                except ValueError:
                    abort(400, "Choose a valid network profile")
                network = db.get(Network, network_id)
                if network is None:
                    abort(400, "Unknown network profile")
                node.network = network
            else:
                node.network = None
            _record_change(db, current_user() or "", f"Changed network for node {node.node_number}",
                           {"record": "node", "node_number": node.node_number,
                            "network_key": node.network.stable_key if node.network else None})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/settings/network-selection")
    @write_required
    def network_selection():
        require_network_profiles()
        enabled = "true" if request.form.get("enabled") == "true" else "false"
        with sessions.begin() as db:
            row = db.get(Setting, "advanced_node_networks")
            if row is None:
                db.add(Setting(key="advanced_node_networks", value=enabled))
            else:
                row.value = enabled
            _record_change(db, current_user() or "", "Changed per-node network selection setting",
                           {"record": "setting", "key": "advanced_node_networks", "value": enabled})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("networks_page"))

    @app.post("/settings/default-network")
    @write_required
    def default_network():
        require_network_profiles()
        with sessions.begin() as db:
            multi_network = db.get(Setting, "advanced_node_networks")
            if multi_network is None or multi_network.value != "true":
                abort(404)
            network = db.get(Network, request.form.get("network_id", type=int))
            if network is None:
                abort(400, "Choose an existing network profile")
            row = db.get(Setting, "default_network_key")
            if row is None:
                db.add(Setting(key="default_network_key", value=network.stable_key))
            else:
                row.value = network.stable_key
            _record_change(db, current_user() or "", f"Selected {network.name} as the default network",
                           {"record": "setting", "key": "default_network_key",
                            "network_key": network.stable_key})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("networks_page"))

    @app.post("/networks/import")
    @write_required
    def import_network():
        require_network_profiles()
        if request.form.get("action") == "commit":
            profile = _network_profile_from_form(request.form)
        else:
            uploaded = request.files.get("network")
            if uploaded is None:
                abort(400, "Choose a network JSON file")
            try:
                profile = json.loads(uploaded.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                abort(400, "Network file must contain valid UTF-8 JSON")
        try:
            profile = parse_network_profile(profile)
        except ValueError as exc:
            abort(400, str(exc))
        stable_key, name = profile["key"], profile["name"]
        with sessions() as db:
            exists = db.scalar(select(Network.id).where(Network.stable_key == stable_key)) is not None
        if request.form.get("action") != "commit":
            return render_template("network-preview.html", profile=profile, exists=exists,
                                   source="upload", field_definitions=NETWORK_FIELD_DEFINITIONS)
        with sessions.begin() as db:
            network = db.scalar(select(Network).where(Network.stable_key == stable_key))
            if network is None:
                network = Network(stable_key=stable_key, name=name.strip(), schema_version=2,
                                  **network_fields(profile))
                db.add(network)
            else:
                network.name, network.schema_version = name.strip(), 2
                for key, value in network_fields(profile).items():
                    setattr(network, key, value)
            _record_change(db, current_user() or "", f"Imported network profile {name.strip()}",
                           {"record": "network", "stable_key": stable_key, "operation": "upsert"})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("networks_page"))

    @app.post("/networks/manual")
    @write_required
    def create_network():
        require_network_profiles()
        profile = _network_profile_from_form(request.form)
        stable_key, name = profile["key"], profile["name"]
        with sessions() as db:
            exists = db.scalar(select(Network.id).where(Network.stable_key == stable_key)) is not None
        if exists:
            abort(409, "That network key already exists; use profile upload to update it")
        if request.form.get("action") != "commit":
            return render_template("network-preview.html", profile=profile,
                                   exists=False, source="manual",
                                   field_definitions=NETWORK_FIELD_DEFINITIONS)
        with sessions.begin() as db:
            db.add(Network(stable_key=stable_key, name=name, schema_version=2,
                           **network_fields(profile)))
            _record_change(db, current_user() or "", f"Added network profile {name}",
                           {"record": "network", "stable_key": stable_key, "operation": "create"})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("networks_page"))

    @app.get("/files")
    @login_required
    def files():
        return render_template("files.html", filenames=GENERATED_FILES)

    @app.route("/diagnostics", methods=["GET", "POST"])
    @login_required
    def diagnostics():
        choices = ("core show version", "core show uptime", "core show channels",
                   "iax2 show peers", "rpt show nodes", "module show")
        output = None
        selected = None
        error = None
        if request.method == "POST":
            selected = request.form.get("command")
            if selected not in choices:
                abort(400, "Choose a supported diagnostic")
            try:
                output = _request_diagnostic(settings, selected)
            except OSError as exc:
                error = str(exc)
        return render_template("diagnostics.html", choices=choices, output=output,
                               selected=selected, error=error, app_version=__version__)

    @app.route("/files/<filename>", methods=["GET", "POST"])
    @login_required
    def edit_file(filename: str):
        if filename not in GENERATED_FILES:
            abort(404)
        if request.method == "GET":
            current = render_database(
                settings.database, network_profiles_enabled=settings.network_profiles_enabled,
                default_network=settings.default_network).get(filename, b"").decode("utf-8")
            current = _mask_secrets(current)
            return render_template("editor.html", filename=filename, content=current,
                                   preview=None, error=None, can_write=current_user() in writers())
        if current_user() not in writers():
            abort(403)
        content = request.form.get("content", "")
        values, preserved = parse_config(filename, content)
        summary = {
            "settings": sum(len(entries) for entries in values.values()),
            "preserved": sum(len(lines) for lines in preserved.values()),
        }
        if request.form.get("action") == "preview":
            current = render_database(
                settings.database, network_profiles_enabled=settings.network_profiles_enabled,
                default_network=settings.default_network).get(filename, b"").decode("utf-8")
            diff = "\n".join(difflib.unified_diff(
                _mask_secrets(current).splitlines(), _mask_secrets(content).splitlines(),
                fromfile=f"current/{filename}", tofile=f"candidate/{filename}", lineterm=""))
            preview_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return render_template("editor.html", filename=filename, content=content,
                                   preview=summary, diff=diff, preview_hash=preview_hash,
                                   error=None, can_write=True)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if (request.form.get("action") != "commit" or request.form.get("confirmed") != "yes"
                or request.form.get("preview_hash") != content_hash):
            abort(400, "Preview the changes and confirm the commit")
        with sessions.begin() as db:
            try:
                _save_config_file(db, filename, values, preserved)
            except ValueError as exc:
                abort(400, str(exc))
            _record_change(db, current_user() or "", f"Updated {filename}",
                           {"record": "configuration_file", "filename": filename,
                            "settings_count": summary["settings"],
                            "preserved_lines_count": summary["preserved"]})
        dispose_database_engine(settings.database)
        _regenerate_or_503(settings)
        return redirect(url_for("edit_file", filename=filename))

    @app.get("/backup")
    @write_required
    def backup():
        if not database_exists(settings.database):
            abort(404)
        snapshot = _sqlite_snapshot(settings.database)
        response = send_file(snapshot, as_attachment=True,
                             download_name="asterisk-node-manager.sqlite3", mimetype="application/vnd.sqlite3")
        response.direct_passthrough = False
        response.call_on_close(lambda: snapshot.unlink(missing_ok=True))
        return response

    @app.post("/restore")
    @write_required
    def restore():
        uploaded = request.files.get("database")
        if uploaded is None or not uploaded.filename:
            abort(400, "Choose a SQLite backup file")
        memory_database = is_memory_database(settings.database)
        database_path = None if memory_database else Path(settings.database)
        if database_path is not None:
            database_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=(database_path.parent if database_path else None),
                                         delete=False) as temp:
            temp_path = Path(temp.name)
            uploaded.save(temp)
        previous = _sqlite_snapshot(settings.database) if database_exists(settings.database) else None
        try:
            try:
                with sqlite3.connect(f"file:{temp_path}?mode=ro", uri=True) as conn:
                    check = conn.execute("PRAGMA integrity_check").fetchone()
                    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
                    if check is None or check[0] != "ok" or version is None:
                        abort(400, "Backup is missing migration metadata")
            except sqlite3.Error:
                abort(400, "Backup is not a valid Asterisk Node Manager database")
            if previous is not None and database_path is not None:
                current_stat = database_path.stat()
                try:
                    os.chown(temp_path, current_stat.st_uid, current_stat.st_gid)
                except PermissionError:
                    pass
                else:
                    os.chmod(temp_path, current_stat.st_mode & 0o777)
            restore_sqlite_snapshot(settings.database, temp_path)
            dispose_database_engine(settings.database)
            try:
                upgrade_database(settings.database)
                _request_generation(settings)
            except Exception:
                if previous is not None and previous.exists():
                    restore_sqlite_snapshot(settings.database, previous)
                elif database_path is not None:
                    database_path.unlink(missing_ok=True)
                dispose_database_engine(settings.database)
                raise
        finally:
            temp_path.unlink(missing_ok=True)
            if previous is not None:
                previous.unlink(missing_ok=True)
        return redirect(url_for("index"))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def _request_generation(settings: Settings) -> None:
    if settings.demo_mode:
        _write_demo_files(settings.demo_output_directory, render_database(
            settings.database, network_profiles_enabled=settings.network_profiles_enabled,
            default_network=settings.default_network))
        return
    request_data = json.dumps({"operation": "generate"}).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(str(settings.writer_socket))
        client.sendall(request_data + b"\n")
        response = _read_writer_response(client)
    if not response.get("ok"):
        raise OSError(response.get("error", "configuration generation failed"))


def _request_authentication(settings: Settings, username: str, password: str) -> bool:
    if settings.demo_mode:
        return username == DEMO_USERNAME
    request_data = json.dumps({"operation": "authenticate", "username": username,
                               "password": password, "service": settings.pam_service}).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(str(settings.writer_socket))
        client.sendall(request_data + b"\n")
        response = _read_writer_response(client)
    return bool(response.get("authenticated"))


def _request_diagnostic(settings: Settings, command: str) -> str:
    if settings.demo_mode:
        return _demo_diagnostic(command)
    request_data = json.dumps({"operation": "diagnostic", "command": command}).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(str(settings.writer_socket))
        client.sendall(request_data + b"\n")
        response = _read_writer_response(client)
    if not response.get("ok"):
        raise OSError(response.get("error", "Asterisk diagnostic failed"))
    return str(response.get("output", ""))


def _demo_diagnostic(command: str) -> str:
    examples = {
        "core show version": "Asterisk 20.7.0-demo built for demonstration\n",
        "core show uptime": "System uptime: 2 hours, 14 minutes\nLast reload: 18 minutes ago\n",
        "core show channels": "Channel              Location             State   Application\n0 active channels\n",
        "iax2 show peers": "Name/Username    Host             State\nDemoPeer         192.0.2.25       OK\n",
        "rpt show nodes": "Node 1000: Demo Node North\nNode 1001: Demo Node South\n",
        "module show": "Module                         Description\napp_rpt.so                     Radio Repeater\n",
    }
    return examples.get(command, "No demonstration output for this command.\n")


def _write_demo_files(directory: Path, files: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    originals: dict[str, bytes | None] = {}
    staged: dict[str, Path] = {}
    try:
        for name, content in files.items():
            if Path(name).name != name:
                raise ValueError("unsafe generated filename")
            target = directory / name
            originals[name] = target.read_bytes() if target.exists() else None
            with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o644)
            staged[name] = temporary
        for name, temporary in staged.items():
            os.replace(temporary, directory / name)
    except Exception:
        for name, original in originals.items():
            target = directory / name
            if original is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(original)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def _safe_local_redirect(target: str | None) -> str | None:
    if not target:
        return None
    parsed = urlsplit(target)
    if (parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//")
            or "\\" in target or any(ord(char) < 32 for char in target)):
        return None
    return target


def _network_profile_from_form(form) -> dict:
    profile = {"schema_version": 2, "key": form.get("key", "").strip(),
               "name": form.get("name", "").strip()}
    for definition in NETWORK_FIELD_DEFINITIONS:
        key = definition["key"]
        raw = form.get(key, "")
        if definition["type"] == "boolean":
            profile[key] = raw in {"true", "yes", "1", "on"}
        elif definition["type"] == "number":
            try:
                profile[key] = int(raw)
            except (TypeError, ValueError):
                profile[key] = raw
        else:
            profile[key] = raw.strip()
    try:
        return parse_network_profile(profile)
    except ValueError as exc:
        abort(400, str(exc))


def _read_writer_response(client: socket.socket) -> dict:
    chunks = bytearray()
    try:
        while True:
            chunk = client.recv(16384)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > 1_048_576:
                raise OSError("writer response exceeds the 1 MiB limit")
        if not chunks:
            raise OSError("writer closed the connection without a response")
        response = json.loads(chunks.decode("utf-8"))
        if not isinstance(response, dict):
            raise OSError("writer returned a non-object response")
        return response
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, OSError):
            raise
        raise OSError("invalid or incomplete response from writer") from exc


def _sqlite_snapshot(database: str | Path) -> Path:
    return sqlite_snapshot(database)


def _record_change(db, actor: str, summary: str, details: dict | None = None) -> None:
    latest = db.scalar(select(func.max(Change.revision))) or 0
    db.add(Change(actor=actor, summary=summary, revision=latest + 1, details=details or {}))


def _save_config_file(db, filename: str, values: dict, preserved: dict) -> None:
    prior_values = {(row.section, row.key): row for row in
                    db.scalars(select(ConfigValue).where(ConfigValue.file_name == filename))}
    prior_custom = {}
    for row in db.scalars(select(CustomLine).where(CustomLine.file_name == filename)
                          .order_by(CustomLine.section, CustomLine.line_number)):
        prior_custom.setdefault(row.section, []).append(row.content)
    db.query(ConfigValue).filter_by(file_name=filename).delete()
    db.query(CustomLine).filter_by(file_name=filename).delete()
    if filename == "rpt.conf":
        existing_nodes = {str(node.node_number): node for node in db.scalars(select(Node))}
        retained: set[str] = set()
        for section, entries in values.items():
            if section.isdigit():
                retained.add(section)
                node = existing_nodes.get(section)
                if node is None:
                    node = Node(node_number=int(section), name=f"Node {section}")
                    db.add(node)
                apply_node_config_values(node, entries)
                for key, value in entries.items():
                    if key in NODE_CONFIG_FIELDS:
                        continue
                    previous = prior_values.get((section, key))
                    if value == SECRET_VALUE and previous is not None and previous.secret:
                        value = previous.value
                    db.add(ConfigValue(file_name=filename, section=section, key=key, value=value,
                                       secret=is_secret_key(key)))
                continue
            for key, value in entries.items():
                previous = prior_values.get((section, key))
                if value == SECRET_VALUE and previous is not None and previous.secret:
                    value = previous.value
                db.add(ConfigValue(file_name=filename, section=section, key=key, value=value,
                                   secret=is_secret_key(key)))
        for section, node in existing_nodes.items():
            if section not in retained:
                db.delete(node)
    else:
        usb_fields = node_fields_for_file("simpleusb.conf")
        radio_fields = node_fields_for_file("usbradio.conf")
        for section, entries in values.items():
            if filename in {"simpleusb.conf", "usbradio.conf"} and section.isdigit():
                node = db.query(Node).filter_by(node_number=int(section)).one_or_none()
                if node is None:
                    node = Node(node_number=int(section), name=f"Node {section}")
                    db.add(node)
                is_radio = filename == "usbradio.conf"
                known_fields = radio_fields if is_radio else usb_fields
                relation_name = "usbradio_settings" if is_radio else "simpleusb_settings"
                settings_type = USBRadioSettings if is_radio else SimpleUSBSettings
                typed = getattr(node, relation_name)
                if typed is None:
                    typed = settings_type()
                    setattr(node, relation_name, typed)
                typed_values = {}
                for key, value in entries.items():
                    if key not in known_fields:
                        previous = prior_values.get((section, key))
                        if value == SECRET_VALUE and previous is not None and previous.secret:
                            value = previous.value
                        db.add(ConfigValue(file_name=filename, section=section, key=key, value=value,
                                           secret=is_secret_key(key)))
                    else:
                        typed_values[key] = value
                apply_interface_config_values(typed, filename, typed_values)
                continue
            for key, value in entries.items():
                previous = prior_values.get((section, key))
                if value == SECRET_VALUE and previous is not None and previous.secret:
                    value = previous.value
                db.add(ConfigValue(file_name=filename, section=section, key=key, value=value,
                                   secret=is_secret_key(key)))
    for section, lines in preserved.items():
        original_registrations = [line for line in prior_custom.get(section, [])
                                  if re.match(r"^\s*register\s*=>", line, re.IGNORECASE)]
        registration_index = 0
        for index, line in enumerate(lines):
            if re.match(r"^\s*register\s*=>", line, re.IGNORECASE):
                if re.match(r"^\s*register\s*=>\s*\[hidden\]\s*$", line, re.IGNORECASE):
                    if registration_index >= len(original_registrations):
                        raise ValueError("A hidden registration could not be matched to its original value")
                    line = original_registrations[registration_index]
                registration_index += 1
            db.add(CustomLine(file_name=filename, section=section, line_number=index, content=line))


def _mask_secrets(text: str) -> str:
    masked = []
    for line in text.splitlines():
        match = re.match(r"^(\s*)(.*?)\s*(=>|=)\s*(.*)$", line)
        if match and not line.lstrip().startswith((";", "#")):
            indent, key, separator, value = match.groups()
            if is_secret_key(key.strip()) and value.strip():
                line = f"{indent}{key} {separator} {SECRET_VALUE}"
        masked.append(line)
    return "\n".join(masked) + ("\n" if text.endswith("\n") else "")


def _regenerate_or_503(settings: Settings) -> None:
    try:
        _request_generation(settings)
    except OSError as exc:
        abort(503, f"Configuration change was rolled back because file generation failed: {exc}. Retry the change or run `astnode generate` as root after resolving the writer error.")


def _read_secret(path: Path, demo_mode: bool = False) -> str:
    try:
        value = path.read_text().strip()
        if value:
            return value
    except OSError:
        pass
    if demo_mode:
        return "demo-mode-only-session-key-change-me"
    if os.environ.get("ASTERISK_NODE_MANAGER_DEV") == "1":
        return "development-only-change-me"
    raise RuntimeError(f"Missing Flask secret key: {path}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    mode = "demo" if settings.demo_mode else "normal"
    logger.info("Starting node-manager web service in %s mode", mode)
    app = create_app(settings)
    if not settings.demo_mode:
        _request_generation(settings)
    logger.info("Listening on http://%s:%d", settings.listen_address, settings.port)
    serve(app, host=settings.listen_address, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
