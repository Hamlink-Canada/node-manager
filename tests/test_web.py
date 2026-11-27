import hashlib
import json
from io import BytesIO

import pytest
from sqlalchemy import func, select

from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import (
    is_memory_database,
    session_factory,
    sqlite_snapshot,
)
from asterisk_node_manager.migrate import upgrade_database
from asterisk_node_manager.models import (Change, ConfigValue, CustomLine, CustomValue, Network,
                                          Node, Setting, SimpleUSBSettings, USBRadioSettings)
from asterisk_node_manager.web import create_app


def _dispose(sessions, database):
    if not is_memory_database(database):
        sessions.kw["bind"].dispose()


def _network_profile(key, name, **overrides):
    profile = {
        "schema_version": 2, "key": key, "name": name,
        "registration_method": "http", "http_registration_server": "",
        "iax_registration_server": "", "iax_registration_port": 4569,
        "stats_enabled": False, "stats_post_url": "", "stats_post_interval": 60,
        "node_lookup_method": "both", "dns_node_domain": "",
        "max_dns_node_length": 6, "external_node_file": "",
    }
    profile.update(overrides)
    return profile


def test_demo_mode_login_and_node_configuration_work_without_writer_socket(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated", writer_socket=tmp_path / "absent.sock")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()

    login = client.post("/login")
    assert login.status_code == 302
    assert client.get("/").status_code == 200
    assert b"Demo Node North" in client.get("/").data

    sessions = session_factory(settings.database)
    with sessions.begin() as session:
        node = session.query(Node).filter_by(node_number=1000).one()
        node.simpleusb_settings.devstr = "usb:1-2"
        node.simpleusb_settings.serial = "SN-12345"
        default_hangtime = session.query(ConfigValue).filter_by(
            file_name="rpt.conf", section="node-main", key="hangtime").one_or_none()
        if default_hangtime is None:
            session.add(ConfigValue(file_name="rpt.conf", section="node-main", key="hangtime",
                                    default_value="6000", secret=False))
        else:
            default_hangtime.value = "6000"
    overview = client.get("/")
    assert b"USB device" in overview.data
    assert b"Identifier:" in overview.data
    assert b"usb:1-2" in overview.data
    assert b"SN-12345" in overview.data

    try:
        with sessions() as session:
            node_id = session.query(Node).filter_by(node_number=1000).one().id
        response = client.get(f"/nodes/{node_id}/configuration")
        assert response.status_code == 200
        assert b"Advanced settings" in response.data
        assert b'data-reset-default="field-hangtime"' in response.data
        assert b'Default: <code>6000</code>' in response.data
        assert b'data-interface-panel="SimpleUSB"' in response.data
        assert b'data-interface-panel="Radio" hidden' in response.data
        assert b'name="usbradio_rxdemod"' in response.data
        saved = client.post(f"/nodes/{node_id}/configuration", data={
            "rxchannel": "SimpleUSB/1000", "duplex": "0", "hangtime": "5000",
            "simpleusb_devstr": "usb:1-2", "simpleusb_serial": "SN-12345",
            "linktolink": "yes", "advanced_view": "yes",
        })
        assert saved.status_code == 302
        with sessions() as session:
            node = session.get(Node, node_id)
            assert node.hangtime == 5000
            assert node.duplex == 0
            assert node.simpleusb_settings.devstr == "usb:1-2"
            assert node.simpleusb_settings.serial == "SN-12345"
        generated_rpt = (settings.demo_output_directory / "rpt.conf").read_text()
        assert "linktolink = yes" in generated_rpt
        assert "duplex = 0" in generated_rpt
        generated_simpleusb = (settings.demo_output_directory / "simpleusb.conf").read_text()
        assert "rxboost = no" in generated_simpleusb
        assert "devstr = usb:1-2" in generated_simpleusb
        assert "serial = SN-12345" in generated_simpleusb
        switched = client.post(f"/nodes/{node_id}/configuration", data={
            "rxchannel": "Radio/1000", "duplex": "0", "hangtime": "5000",
            "usbradio_rxdemod": "speaker", "usbradio_rxvoiceadj": "0.625",
            "advanced_view": "yes",
        })
        assert switched.status_code == 302
        with sessions() as session:
            node = session.get(Node, node_id)
            assert node.usbradio_settings.rxdemod == "speaker"
            assert node.usbradio_settings.rxvoiceadj == "0.625"
        generated_radio = (settings.demo_output_directory / "usbradio.conf").read_text()
        assert "rxdemod = speaker" in generated_radio
        assert "rxvoiceadj = 0.625" in generated_radio
    finally:
        _dispose(sessions, settings.database)


def test_non_demo_routes_require_login_and_writers_file(tmp_path):
    settings = Settings(database=tmp_path / "web.sqlite3", writer_allowlist=tmp_path / "writers",
                        secret_key_file=tmp_path / "secret", writer_socket=tmp_path / "missing.sock")
    settings.writer_allowlist.write_text("writer\n")
    settings.secret_key_file.write_text("test-only-secret-key")
    upgrade_database(settings.database)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()

    assert client.get("/").status_code == 302
    assert client.get("/changes").status_code == 302
    with client.session_transaction() as browser_session:
        browser_session["username"] = "reader"
    assert client.get("/").status_code == 200
    assert client.get("/nodes/setup").status_code == 403
    assert client.post("/nodes", data={"node_number": "1200", "name": "Unauthorized"}).status_code == 403
    assert client.get("/backup").status_code == 403
    assert b"Download backup" not in client.get("/").data


def test_profile_availability_is_read_only_dynaconf_configuration(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated",
                        network_profiles_enabled=False)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    assert client.get("/networks").status_code == 404
    assert client.get("/settings").status_code == 404
    assert b'id="networksMenu"' not in client.get("/").data
    assert client.post("/settings", data={"network_profiles_enabled": "true"}).status_code == 404
    assert client.post("/settings/network-selection", data={"enabled": "true"}).status_code == 404


def test_guided_node_setup_commits_typed_settings_and_regenerates_once(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    page = client.get("/nodes/setup")
    assert page.status_code == 200
    assert b"Nothing is saved until you finish the review" in page.data
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            assert session.query(Node).filter_by(node_number=2345).count() == 0

        created = client.post("/nodes/setup", data={
            "node_number": "2345",
            "name": "Workshop Repeater",
            "callsign": "VE3ABC",
            "profile": "full_duplex_repeater",
            "interface": "SimpleUSB",
        })
        assert created.status_code == 302
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=2345).one()
            assert node.name == "Workshop Repeater"
            assert node.rxchannel == "SimpleUSB/2345"
            assert node.duplex is None
            assert node.idrecording == "|iVE3ABC"
            assert node.simpleusb_settings is not None

        generated = (settings.demo_output_directory / "rpt.conf").read_text()
        assert "[2345]" in generated
        assert "idrecording = |iVE3ABC" in generated
        assert "rxchannel = SimpleUSB/2345" in generated

        radio = client.post("/nodes/setup", data={
            "node_number": "2347",
            "name": "USB Radio Repeater",
            "callsign": "VE3XYZ",
            "profile": "full_duplex_repeater",
            "interface": "Radio",
        })
        assert radio.status_code == 302
        with sessions() as session:
            radio_node = session.query(Node).filter_by(node_number=2347).one()
            assert radio_node.usbradio_settings is not None
            assert session.query(USBRadioSettings).join(Node).filter(
                Node.node_number == 2347).count() == 1
        generated_radio = (settings.demo_output_directory / "usbradio.conf").read_text()
        assert "[2347]" in generated_radio
        assert "rxdemod = flat" in generated_radio

        hub = client.post("/nodes/setup", data={
            "node_number": "2346",
            "name": "Remote Hub",
            "callsign": "VE3XYZ",
            "profile": "hub_no_radio",
            "interface": "SimpleUSB",
        })
        assert hub.status_code == 302
        with sessions() as session:
            hub_node = session.query(Node).filter_by(node_number=2346).one()
            assert hub_node.rxchannel is None
            assert hub_node.duplex == 0
            assert hub_node.simpleusb_settings is None
    finally:
        _dispose(sessions, settings.database)


def test_guided_node_setup_rejects_duplicate_node_id_without_changing_it(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    response = client.post("/nodes/setup", data={
        "node_number": "1000",
        "name": "Duplicate",
        "callsign": "VE3ABC",
        "profile": "simplex_hotspot",
        "interface": "SimpleUSB",
    })
    assert response.status_code == 200
    assert b"That Node ID is already configured." in response.data


def test_node_creation_requires_at_least_four_digit_node_id(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    guided = client.post("/nodes/setup", data={
        "node_number": "123", "name": "Short ID", "callsign": "VE3ABC",
        "profile": "simplex_hotspot", "interface": "SimpleUSB",
    })
    assert guided.status_code == 200
    assert b"at least four digits" in guided.data
    assert client.post("/nodes", data={"node_number": "123", "name": "Short ID"}).status_code == 400
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            assert session.query(Node).filter_by(node_number=1000).count() == 1
    finally:
        _dispose(sessions, settings.database)


def test_network_profile_upload_validates_and_updates_by_stable_key(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated",
                        network_profiles_enabled=True)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    profile = _network_profile("example.net", "Example network",
                               registration_method="iax", iax_registration_server="example.invalid",
                               iax_registration_port=4570, stats_enabled=True,
                               stats_post_url="https://stats.example.net/update",
                               node_lookup_method="dns", dns_node_domain="nodes.example.net")
    preview = client.post("/networks/import", data={
        "network": (BytesIO(json.dumps(profile).encode()), "example.json")
    }, content_type="multipart/form-data")
    assert preview.status_code == 200
    assert b"Example network" in preview.data

    committed = client.post("/networks/import", data={
        "action": "commit", "schema_version": "2", **{
            key: ("true" if value else "false") if isinstance(value, bool) else str(value)
            for key, value in profile.items()},
    })
    assert committed.status_code == 302
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            original = session.query(Network).filter_by(stable_key="example.net").one()
            original_id = original.id

        replacement = client.post("/networks/import", data={
            "action": "commit", **{
                key: ("true" if value else "false") if isinstance(value, bool) else str(value)
                for key, value in _network_profile("example.net", "Updated network",
                    registration_method="http", http_registration_server="updated.invalid").items()},
        })
        assert replacement.status_code == 302
        with sessions() as session:
            network = session.query(Network).filter_by(stable_key="example.net").one()
            assert network.id == original_id
            assert network.name == "Updated network"
            assert network.http_registration_server == "updated.invalid"
            assert network.registration_method is None
            assert session.query(Network).filter_by(stable_key="allstarlink").count() == 1
    finally:
        _dispose(sessions, settings.database)


def test_network_add_and_import_are_separate_pages(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated",
                        network_profiles_enabled=True)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    overview = client.get("/networks")
    assert b"href=\"/networks/add\"" in overview.data
    assert b"href=\"/networks/import\"" in overview.data
    assert b'name="config"' not in overview.data
    navbar = client.get("/").data
    assert b'<button class="nav-link dropdown-toggle" type="button" id="nodesMenu"' in navbar
    assert b'<button class="nav-link dropdown-toggle" type="button" id="networksMenu"' in navbar
    assert b'<button class="nav-link dropdown-toggle" type="button" id="toolsMenu"' in navbar
    assert b">Nodes</button>" in navbar
    assert b">Networks</button>" in navbar
    assert b">Tools</button>" in navbar
    assert b'class="dropdown-item" href="/changes">Recent changes</a>' in navbar
    assert navbar.index(b'id="toolsMenu"') < navbar.index(b'href="/changes">Recent changes</a>')
    assert navbar.index(b'href="/changes">Recent changes</a>') < navbar.index(b"</ul>", navbar.index(b'id="toolsMenu"'))
    assert b'class="dropdown-item" href="/files">Configuration files</a>' in navbar
    assert b'<a class="nav-link" href="/changes">' not in navbar
    add_page = client.get("/networks/add")
    assert add_page.status_code == 200
    assert b'value="4569"' in add_page.data
    assert b'data-reset-default="field-iax_registration_port"' in add_page.data
    assert b'Stable key <span class="text-danger">(Required)</span>' in add_page.data
    assert client.get("/networks/import").status_code == 200


def test_recent_changes_have_th…14387 tokens truncated…sts,
                                   source="upload", field_definitions=NETWORK_FIELD_DEFINITIONS)
        with sessions.begin() as db:
            network = db.scalar(select(Network).where(Network.stable_key == stable_key))
            if network is None:
                network = Network(stable_key=stable_key, name=name.strip(), schema_version=2,
                                  **network_overrides(profile))
                db.add(network)
            else:
                network.name, network.schema_version = name.strip(), 2
                _store_network_overrides(network, profile)
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
                           **network_overrides(profile)))
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
            except (OSError, OperationError) as exc:
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

    @app.get("/api/live-operations")
    @write_required
    def live_operation_catalog():
        return {"drivers": operation_names(),
                "operations": ["list_devices", "read_settings", "set_value", "reload_driver"],
                "transmit_confirmation_required": {"usbradio": ["txvoice", "txtone"]}}

    @app.post("/api/live-operations")
    @write_required
    def submit_live_operation():
        if request.content_length is not None and request.content_length > 16_384:
            return jsonify(error="Request body exceeds the 16 KiB limit."), 413
        try:
            raw_payload = request.stream.read(16_385)
            if len(raw_payload) > 16_384:
                return jsonify(error="Request body exceeds the 16 KiB limit."), 413
            payload = json.loads(raw_payload)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            payload = None
        if not isinstance(payload, dict):
            return jsonify(error="A JSON object is required."), 400
        allowed = {"driver", "operation", "node_number", "setting", "value", "confirm_transmit"}
        if set(payload) - allowed:
            return jsonify(error="Unknown request fields are not allowed."), 400
        driver = payload.get("driver")
        operation = payload.get("operation")
        if not isinstance(driver, str) or driver not in {"simpleusb", "usbradio"}:
            return jsonify(error="driver must be 'simpleusb' or 'usbradio'."), 400
        if not isinstance(operation, str) or operation not in {
                "list_devices", "read_settings", "set_value", "reload_driver"}:
            return jsonify(error="operation must be list_devices, read_settings, set_value, or reload_driver."), 400
        node_number = payload.get("node_number")
        device = None
        if node_number is not None and (isinstance(node_number, bool)
                                        or not isinstance(node_number, int)
                                        or not 1000 <= node_number <= 2**63 - 1):
            return jsonify(error="node_number must be an integer from 1000 to 2^63 - 1."), 400
        if operation not in {"list_devices", "reload_driver"}:
            if node_number is None:
                return jsonify(error="node_number must be an integer from 1000 to 2^63 - 1."), 400
            with sessions() as db:
                node = db.scalar(select(Node).where(Node.node_number == node_number))
                if node is None:
                    return jsonify(error="Node Number is not configured."), 404
                channel = node_config_values(node, _stored_defaults(db, "rpt.conf"))["rxchannel"]
            prefix = "SimpleUSB/" if driver == "simpleusb" else "Radio/"
            if not channel.startswith(prefix):
                return jsonify(error=f"Node {node_number} is not configured for {driver}."), 400
            device = channel[len(prefix):]
        if operation == "set_value":
            if not isinstance(payload.get("setting"), str) or "value" not in payload:
                return jsonify(error="set_value requires setting and value."), 400
            confirm_transmit = payload.get("confirm_transmit", False)
            if not isinstance(confirm_transmit, bool):
                return jsonify(error="confirm_transmit must be a boolean."), 400
            if driver == "usbradio" and payload["setting"] in {"txvoice", "txtone"} \
                    and confirm_transmit is not True:
                return jsonify(error=("confirm_transmit must be true because this USBRadio "
                                      "operation keys the transmitter.")), 400
        elif payload.get("confirm_transmit", False) is not False:
            return jsonify(error="confirm_transmit is only accepted for set_value."), 400
        try:
            task = live_tasks.submit(current_user() or "", driver, operation, node_number,
                                     device, payload.get("setting"), payload.get("value"),
                                     payload.get("confirm_transmit", False))
        except OperationError as exc:
            return jsonify(error=str(exc)), 400
        except queue.Full as exc:
            return jsonify(error=str(exc)), 503, {"Retry-After": "2"}
        return jsonify(task), 202

    @app.get("/api/live-operations/<task_id>")
    @write_required
    def poll_live_operation(task_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", task_id):
            return jsonify(error="Task was not found."), 404
        task = live_tasks.get(task_id, current_user() or "")
        if task is None:
            return jsonify(error="Task was not found."), 404
        return jsonify(task)

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
    allowed = {"core show version", "core show uptime", "core show channels",
               "iax2 show peers", "rpt show nodes", "module show"}
    if command not in allowed:
        raise OperationError("Diagnostic command is not allowed.")
    return AsteriskSocket(settings.asterisk_socket).run(command)


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


def _store_network_overrides(network: Network, profile: dict) -> None:
    overrides = network_overrides(profile)
    for key in NETWORK_DEFAULTS:
        setattr(network, key, overrides.get(key))


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


def _stored_defaults(db, filename: str) -> dict[str, str]:
    primary_rows = db.scalars(select(ConfigValue).where(
        ConfigValue.file_name == filename,
        ConfigValue.section.in_(("node-main", "node-main(!)")))).all()
    custom_rows = db.scalars(select(CustomValue).where(
        CustomValue.file_name == filename,
        CustomValue.section.in_(("node-main", "node-main(!)")))).all()
    defaults = {row.key: row.value for row in primary_rows}
    defaults.update({row.key: row.value for row in custom_rows})
    return defaults


def _save_config_file(db, filename: str, values: dict, preserved: dict) -> None:
    prior_values = {(row.section, row.key): row for row in
                    db.scalars(select(ConfigValue).where(ConfigValue.file_name == filename))}
    prior_values.update({(row.section, row.key): row for row in
                         db.scalars(select(CustomValue).where(CustomValue.file_name == filename))})
    submitted_defaults = {row.key: row.value for row in db.scalars(select(ConfigValue).where(
        ConfigValue.file_name == filename,
        ConfigValue.section.in_(("node-main", "node-main(!)")))).all()}
    submitted_defaults.update({key: value for section, entries in values.items()
                               if section in {"node-main", "node-main(!)"}
                               for key, value in entries.items()})
    prior_custom = {}
    for row in db.scalars(select(CustomLine).where(CustomLine.file_name == filename)
                          .order_by(CustomLine.section, CustomLine.line_number)):
        prior_custom.setdefault(row.section, []).append(row.content)
    default_lines = Counter(
        (row.section, row.content.strip())
        for row in db.scalars(select(CustomLine).where(
            CustomLine.file_name == filename, CustomLine.is_default.is_(True)))
        if row.content.strip())
    db.query(CustomValue).filter_by(file_name=filename).delete()
    db.query(CustomLine).filter_by(file_name=filename, is_default=False).delete()
    sections_with_codec_directives = {
        section for section, lines in preserved.items()
        if any(re.match(r"^\s*(?:allow|disallow)\s*(?:=>|=)", line, re.IGNORECASE)
               for line in lines)
    }
    for default_line in db.scalars(select(CustomLine).where(
            CustomLine.file_name == filename, CustomLine.is_default.is_(True))):
        if re.match(r"^\s*(?:allow|disallow)\s*(?:=>|=)",
                    default_line.content, re.IGNORECASE):
            default_line.is_deleted = default_line.section in sections_with_codec_directives
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
                apply_node_config_values(node, entries, submitted_defaults)
                for key, value in entries.items():
                    if key in NODE_CONFIG_FIELDS:
                        continue
                    previous = prior_values.get((section, key))
                    if value == SECRET_VALUE and previous is not None and previous.secret:
                        value = previous.value
                    _set_custom_value(db, filename, section, key, value)
                continue
            for key, value in entries.items():
                previous = prior_values.get((section, key))
                if value == SECRET_VALUE and previous is not None and previous.secret:
                    value = previous.value
                _set_custom_value(db, filename, section, key, value)
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
                        _set_custom_value(db, filename, section, key, value)
                    else:
                        typed_values[key] = value
                apply_interface_config_values(typed, filename, typed_values,
                                              submitted_defaults)
                continue
            for key, value in entries.items():
                previous = prior_values.get((section, key))
                if value == SECRET_VALUE and previous is not None and previous.secret:
                    value = previous.value
                _set_custom_value(db, filename, section, key, value)
    structured_lines = {}
    for section, lines in preserved.items():
        original_registrations = [line for line in prior_custom.get(section, [])
                                  if re.match(r"^\s*register\s*=>", line, re.IGNORECASE)]
        registration_index = 0
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith(";") or (
                    stripped.startswith("#") and not is_asterisk_include(line)):
                continue
            is_structured = ((filename == "modules.conf" and parse_module_directive(line))
                             or (filename == "extensions.conf" and parse_extension_rule(line)))
            if is_structured:
                structured_lines.setdefault(section, []).append(line)
                continue
            if re.match(r"^\s*register\s*=>", line, re.IGNORECASE):
                if re.match(r"^\s*register\s*=>\s*\[hidden\]\s*$", line, re.IGNORECASE):
                    if registration_index >= len(original_registrations):
                        raise ValueError("A hidden registration could not be matched to its original value")
                    line = original_registrations[registration_index]
                registration_index += 1
            if (re.match(r"^\s*(?:allow|disallow)\s*(?:=>|=)", line, re.IGNORECASE)
                    and section in sections_with_codec_directives):
                db.add(CustomLine(file_name=filename, section=section, line_number=index,
                                  content=line, is_default=False))
                continue
            baseline_key = (section, line.strip())
            if default_lines[baseline_key]:
                default_lines[baseline_key] -= 1
                continue
            db.add(CustomLine(file_name=filename, section=section, line_number=index, content=line,
                              is_default=False))
    if filename in {"modules.conf", "extensions.conf"}:
        save_structured_lines(db, filename, structured_lines, replace_defaults=True)


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


def _set_custom_value(db, filename: str, section: str, key: str, value: str) -> None:
    """Store only values that differ from the primary database setting."""
    primary = db.scalar(select(ConfigValue).where(
        ConfigValue.file_name == filename, ConfigValue.section == section,
        ConfigValue.key == key))
    if primary is not None and primary.value == value:
        return
    db.add(CustomValue(file_name=filename, section=section, key=key, value=value,
                       secret=is_secret_key(key)))


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
    # Containers can run this process as PID 1, where default SIGTERM handling
    # is ignored by Linux. Handle both Docker's stop signal and terminal Ctrl+C.
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    serve(app, host=settings.listen_address, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
