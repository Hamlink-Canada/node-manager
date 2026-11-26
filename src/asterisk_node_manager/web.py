"""Flask management interface."""

from __future__ import annotations

import os
import re
import json
import shutil
import socket
import tempfile
from functools import wraps
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import func, select
from waitress import serve

from .config import Settings, load_settings
from .database import session_factory
from .asterisk_config import SECRET_VALUE, is_secret_key, parse_config
from .generate import GENERATED_FILES, render_database
from .models import Change, ConfigValue, CustomLine, Network, Node, Setting
from .migrate import upgrade_database
from . import __version__


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.secret_key = _read_secret(settings.secret_key_file)
    app.config["MAX_CONTENT_LENGTH"] = 104_857_600
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    sessions = session_factory(settings.database)
    engine = sessions.kw["bind"]

    def current_user() -> str | None:
        return session.get("username")

    def writers() -> set[str]:
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

    app.jinja_env.globals["is_writer"] = lambda: current_user() in writers()

    @app.get("/login")
    def login():
        return render_template("login.html", error=None)

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not username or not password or not _request_authentication(settings, username, password):
            return render_template("login.html", error="Login failed"), 401
        session.clear()
        session["username"] = username
        return redirect(request.args.get("next") or url_for("index"))

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
            values = {row.key: row.value for row in db.scalars(select(Setting))}
            changes = db.scalars(select(Change).order_by(Change.revision.desc()).limit(20)).all()
        return render_template("index.html", node_count=node_count, networks=networks,
                               nodes=nodes, username=current_user(),
                               default_network=values.get("default_network_key", ""),
                               advanced_networks=values.get("advanced_node_networks") == "true",
                               changes=changes)

    @app.post("/nodes")
    @write_required
    def create_node():
        try:
            node_number = int(request.form.get("node_number", ""))
        except ValueError:
            abort(400, "Node Number must be an integer")
        name = request.form.get("name", "").strip()
        if node_number < 1 or not name:
            abort(400, "Provide a positive Node Number and a name")
        with sessions.begin() as db:
            db.add(Node(node_number=node_number, name=name, settings={}))
            _record_change(db, current_user() or "", f"Added node {node_number}")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/nodes/<int:node_id>/delete")
    @write_required
    def delete_node(node_id: int):
        with sessions.begin() as db:
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            db.delete(node)
            _record_change(db, current_user() or "", f"Removed node {node.node_number}")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/nodes/<int:node_id>/network")
    @write_required
    def assign_network(node_id: int):
        with sessions.begin() as db:
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            raw_id = request.form.get("network_id", "")
            if raw_id:
                network = db.get(Network, int(raw_id))
                if network is None:
                    abort(400, "Unknown network profile")
                node.network = network
            else:
                node.network = None
            _record_change(db, current_user() or "", f"Changed network for node {node.node_number}")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/settings/network-selection")
    @write_required
    def network_selection():
        enabled = "enabled" if request.form.get("enabled") == "true" else "false"
        with sessions.begin() as db:
            row = db.get(Setting, "advanced_node_networks")
            if row is None:
                db.add(Setting(key="advanced_node_networks", value=enabled))
            else:
                row.value = enabled
            _record_change(db, current_user() or "", "Changed per-node network selection setting")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/settings/default-network")
    @write_required
    def default_network():
        with sessions.begin() as db:
            network = db.get(Network, request.form.get("network_id", type=int))
            if network is None:
                abort(400, "Choose an existing network profile")
            row = db.get(Setting, "default_network_key")
            if row is None:
                db.add(Setting(key="default_network_key", value=network.stable_key))
            else:
                row.value = network.stable_key
            _record_change(db, current_user() or "", f"Selected {network.name} as the default network")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/networks/import")
    @write_required
    def import_network():
        if request.form.get("action") == "commit":
            try:
                profile = {"schema_version": int(request.form.get("schema_version", "1")),
                           "key": request.form.get("key"), "name": request.form.get("name"),
                           "config": json.loads(request.form.get("config", "{}"))}
            except (ValueError, json.JSONDecodeError):
                abort(400, "Invalid network profile preview")
        else:
            uploaded = request.files.get("network")
            if uploaded is None:
                abort(400, "Choose a network JSON file")
            try:
                profile = json.loads(uploaded.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                abort(400, "Network file must contain valid UTF-8 JSON")
        if not isinstance(profile, dict) or profile.get("schema_version") != 1:
            abort(400, "Unsupported network profile schema")
        stable_key, name, config = profile.get("key"), profile.get("name"), profile.get("config")
        if (not isinstance(stable_key, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,120}", stable_key)
                or not isinstance(name, str) or not name.strip() or len(name) > 200
                or not isinstance(config, dict)):
            abort(400, "Network profile needs a key, name, and object config")
        with sessions() as db:
            exists = db.scalar(select(Network.id).where(Network.stable_key == stable_key)) is not None
        if request.form.get("action") != "commit":
            return render_template("network-preview.html", name=name.strip(), stable_key=stable_key,
                                   config_json=json.dumps(config, indent=2), exists=exists,
                                   source="upload")
        with sessions.begin() as db:
            network = db.scalar(select(Network).where(Network.stable_key == stable_key))
            if network is None:
                network = Network(stable_key=stable_key, name=name.strip(), schema_version=1, config=config)
                db.add(network)
            else:
                network.name, network.schema_version, network.config = name.strip(), 1, config
            _record_change(db, current_user() or "", f"Imported network profile {name.strip()}")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/networks/manual")
    @write_required
    def create_network():
        stable_key = request.form.get("key", "").strip()
        name = request.form.get("name", "").strip()
        try:
            config = json.loads(request.form.get("config", "{}"))
        except json.JSONDecodeError:
            abort(400, "Configuration must be valid JSON")
        if (not re.fullmatch(r"[a-zA-Z0-9._-]{1,120}", stable_key)
                or not name or len(name) > 200 or not isinstance(config, dict)):
            abort(400, "Provide a valid key, name, and JSON object configuration")
        with sessions() as db:
            exists = db.scalar(select(Network.id).where(Network.stable_key == stable_key)) is not None
        if exists:
            abort(409, "That network key already exists; use profile upload to update it")
        if request.form.get("action") != "commit":
            return render_template("network-preview.html", name=name, stable_key=stable_key,
                                   config_json=json.dumps(config, indent=2), exists=False, source="manual")
        with sessions.begin() as db:
            db.add(Network(stable_key=stable_key, name=name, schema_version=1, config=config))
            _record_change(db, current_user() or "", f"Added network profile {name}")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

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
            current = render_database(settings.database).get(filename, b"").decode("utf-8")
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
            return render_template("editor.html", filename=filename, content=content,
                                   preview=summary, error=None, can_write=True)
        if request.form.get("action") != "commit" or request.form.get("confirmed") != "yes":
            abort(400, "Preview the changes and confirm the commit")
        with sessions.begin() as db:
            _save_config_file(db, filename, values, preserved)
            _record_change(db, current_user() or "", f"Updated {filename}")
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("edit_file", filename=filename))

    @app.get("/backup")
    @write_required
    def backup():
        if not settings.database.is_file():
            abort(404)
        return send_file(settings.database, as_attachment=True,
                         download_name="asterisk-node-manager.sqlite3", mimetype="application/vnd.sqlite3")

    @app.post("/restore")
    @write_required
    def restore():
        uploaded = request.files.get("database")
        if uploaded is None or not uploaded.filename:
            abort(400, "Choose a SQLite backup file")
        settings.database.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.database.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            uploaded.save(temp)
        previous = settings.database.with_suffix(settings.database.suffix + ".restore-previous")
        try:
            import sqlite3
            try:
                with sqlite3.connect(f"file:{temp_path}?mode=ro", uri=True) as conn:
                    check = conn.execute("PRAGMA integrity_check").fetchone()
                    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
                    if check is None or check[0] != "ok" or version is None:
                        abort(400, "Backup is missing migration metadata")
            except sqlite3.Error:
                abort(400, "Backup is not a valid Asterisk Node Manager database")
            if settings.database.exists():
                shutil.copy2(settings.database, previous)
            os.replace(temp_path, settings.database)
            engine.dispose()
            try:
                upgrade_database(settings.database)
                _request_generation(settings)
            except Exception:
                if previous.exists():
                    os.replace(previous, settings.database)
                else:
                    settings.database.unlink(missing_ok=True)
                engine.dispose()
                raise
        finally:
            temp_path.unlink(missing_ok=True)
            previous.unlink(missing_ok=True)
        return redirect(url_for("index"))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def _request_generation(settings: Settings) -> None:
    request_data = json.dumps({"operation": "generate"}).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(str(settings.writer_socket))
        client.sendall(request_data)
        response = json.loads(client.recv(65536).decode("utf-8"))
    if not response.get("ok"):
        raise OSError(response.get("error", "configuration generation failed"))


def _request_authentication(settings: Settings, username: str, password: str) -> bool:
    request_data = json.dumps({"operation": "authenticate", "username": username,
                               "password": password, "service": settings.pam_service}).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(str(settings.writer_socket))
        client.sendall(request_data)
        response = json.loads(client.recv(65536).decode("utf-8"))
    return bool(response.get("authenticated"))


def _request_diagnostic(settings: Settings, command: str) -> str:
    request_data = json.dumps({"operation": "diagnostic", "command": command}).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(str(settings.writer_socket))
        client.sendall(request_data)
        response = json.loads(client.recv(65536).decode("utf-8"))
    if not response.get("ok"):
        raise OSError(response.get("error", "Asterisk diagnostic failed"))
    return str(response.get("output", ""))


def _record_change(db, actor: str, summary: str) -> None:
    latest = db.scalar(select(func.max(Change.revision))) or 0
    db.add(Change(actor=actor, summary=summary, revision=latest + 1))


def _save_config_file(db, filename: str, values: dict, preserved: dict) -> None:
    prior_values = {(row.section, row.key): row for row in
                    db.scalars(select(ConfigValue).where(ConfigValue.file_name == filename))}
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
                    db.add(Node(node_number=int(section), name=f"Node {section}", settings=entries))
                else:
                    node.settings = _restore_hidden_settings(entries, node.settings)
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
        for section, entries in values.items():
            for key, value in entries.items():
                previous = prior_values.get((section, key))
                if value == SECRET_VALUE and previous is not None and previous.secret:
                    value = previous.value
                db.add(ConfigValue(file_name=filename, section=section, key=key, value=value,
                                   secret=is_secret_key(key)))
    for section, lines in preserved.items():
        for index, line in enumerate(lines):
            db.add(CustomLine(file_name=filename, section=section, line_number=index, content=line))


def _restore_hidden_settings(new: dict[str, str], old: dict[str, str]) -> dict[str, str]:
    result = dict(new)
    for key, value in result.items():
        if value == SECRET_VALUE and key in old and is_secret_key(key):
            result[key] = old[key]
    return result


def _mask_secrets(text: str) -> str:
    masked = []
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith((";", "#")):
            key, value = line.split("=", 1)
            if is_secret_key(key.strip()) and value.strip():
                line = f"{key} = {SECRET_VALUE}"
        masked.append(line)
    return "\n".join(masked) + ("\n" if text.endswith("\n") else "")


def _regenerate_or_503(settings: Settings) -> None:
    try:
        _request_generation(settings)
    except OSError as exc:
        abort(503, f"Database change was saved, but file generation failed: {exc}")


def _read_secret(path: Path) -> str:
    try:
        value = path.read_text().strip()
        if value:
            return value
    except OSError:
        pass
    if os.environ.get("ASTERISK_NODE_MANAGER_DEV") == "1":
        return "development-only-change-me"
    raise RuntimeError(f"Missing Flask secret key: {path}")


def main() -> int:
    settings = load_settings()
    serve(create_app(settings), host=settings.listen_address, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
