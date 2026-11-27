import hashlib
import json
from io import BytesIO

import pytest

from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import (
    is_memory_database,
    session_factory,
    sqlite_snapshot,
)
from asterisk_node_manager.migrate import upgrade_database
from asterisk_node_manager.models import (ConfigValue, CustomLine, Network, Node, Setting,
                                          USBRadioSettings)
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
    try:
        with sessions() as session:
            node_id = session.query(Node).filter_by(node_number=1000).one().id
        response = client.get(f"/nodes/{node_id}/configuration")
        assert response.status_code == 200
        assert b"Advanced settings" in response.data
        assert b'data-interface-panel="SimpleUSB"' in response.data
        assert b'data-interface-panel="Radio" hidden' in response.data
        assert b'name="usbradio_rxdemod"' in response.data
        saved = client.post(f"/nodes/{node_id}/configuration", data={
            "rxchannel": "SimpleUSB/1000", "duplex": "0", "hangtime": "5000",
            "linktolink": "yes", "advanced_view": "yes",
        })
        assert saved.status_code == 302
        generated_rpt = (settings.demo_output_directory / "rpt.conf").read_text()
        assert "linktolink = yes" in generated_rpt
        assert "duplex = 0" in generated_rpt
        assert "rxboost = no" in (settings.demo_output_directory / "simpleusb.conf").read_text()
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
    assert b"Profiles are hidden" in client.get("/settings").data
    assert client.post("/settings", data={"network_profiles_enabled": "true"}).status_code == 405
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
            assert node.duplex == 2
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
            assert session.query(USBRadioSettings).count() == 1
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
            assert hub_node.rxchannel == "Local/pseudo"
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
            assert network.registration_method == "http"
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
    assert client.get("/networks/add").status_code == 200
    assert client.get("/networks/import").status_code == 200


def test_manual_network_form_previews_and_saves_explicit_service_fields(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated",
                        network_profiles_enabled=True)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    profile = _network_profile("manual.example", "Manual Network",
                               registration_method="iax", iax_registration_server="iax.example.net",
                               iax_registration_port=4568, stats_enabled=True,
                               stats_post_url="https://stats.example.net/update",
                               node_lookup_method="both", dns_node_domain="nodes.example.net",
                               max_dns_node_length=7,
                               external_node_file="/var/lib/asterisk/nodes")
    form = {key: ("true" if value else "false") if isinstance(value, bool) else str(value)
            for key, value in profile.items()}
    preview = client.post("/networks/manual", data=form)
    assert preview.status_code == 200
    assert b"IAX registration server" in preview.data
    assert b"nodes.example.net" in preview.data

    saved = client.post("/networks/manual", data={**form, "action": "commit"})
    assert saved.status_code == 302
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            network = session.query(Network).filter_by(stable_key="manual.example").one()
            assert network.registration_method == "iax"
            assert network.iax_registration_port == 4568
            assert network.stats_enabled is True
            assert network.stats_post_url == "https://stats.example.net/update"
            assert network.node_lookup_method == "both"
            assert network.max_dns_node_length == 7
            assert network.external_node_file == "/var/lib/asterisk/nodes"
    finally:
        _dispose(sessions, settings.database)


def test_web_database_backup_and_restore_reverts_later_changes(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    backup = client.get("/backup")
    assert backup.status_code == 200
    backup_bytes = backup.data
    sessions = session_factory(settings.database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=9090, name="Temporary node"))
        _dispose(sessions, settings.database)
        restored = client.post("/restore", data={
            "database": (BytesIO(backup_bytes), "backup.sqlite3")
        }, content_type="multipart/form-data")
        assert restored.status_code == 302
        restored_sessions = session_factory(settings.database)
        with restored_sessions() as session:
            assert session.query(Node).filter_by(node_number=9090).count() == 0
            assert session.query(Node).filter_by(node_number=1000).count() == 1
        _dispose(restored_sessions, settings.database)
    finally:
        _dispose(sessions, settings.database)


def test_file_database_restore_replaces_database_and_allows_a_later_write(monkeypatch, tmp_path):
    settings = Settings(database=tmp_path / "manager.sqlite3",
                        writer_allowlist=tmp_path / "writers",
                        secret_key_file=tmp_path / "secret-key")
    settings.writer_allowlist.write_text("writer\n")
    settings.secret_key_file.write_text("test-secret-key")
    upgrade_database(settings.database)
    sessions = session_factory(settings.database)
    with sessions.begin() as db:
        db.add(Node(node_number=9080, name="Backup node"))
    backup = sqlite_snapshot(settings.database)
    try:
        with sessions.begin() as db:
            db.add(Node(node_number=9081, name="Later node"))
        monkeypatch.setattr("asterisk_node_manager.web._request_generation", lambda _settings: None)
        app = create_app(settings)
        app.config.update(TESTING=True)
        client = app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["username"] = "writer"

        restored = client.post("/restore", data={
            "database": (BytesIO(backup.read_bytes()), "backup.sqlite3")
        }, content_type="multipart/form-data")
        assert restored.status_code == 302
        with sessions() as db:
            assert db.query(Node).filter_by(node_number=9080).one().name == "Backup node"
            assert db.query(Node).filter_by(node_number=9081).count() == 0
        with sessions.begin() as db:
            db.add(Node(node_number=9082, name="Post-restore write"))
        with sessions() as db:
            assert db.query(Node).filter_by(node_number=9082).one().name == "Post-restore write"
    finally:
        backup.unlink(missing_ok=True)
        sessions.kw["bind"].dispose()


def test_demo_memory_database_supports_download_and_restore(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    backup = client.get("/backup")
    assert backup.status_code == 200
    sessions = session_factory(settings.database)
    with sessions.begin() as session:
        session.add(Node(node_number=9091, name="Temporary memory node"))
    response = client.post("/restore", data={
        "database": (BytesIO(backup.data), "backup.sqlite3")
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with session_factory(settings.database)() as session:
        assert session.query(Node).filter_by(node_number=9091).count() == 0
        assert session.query(Node).filter_by(node_number=1000).count() == 1


def test_advanced_simpleusb_file_editor_saves_known_and_unknown_fields(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    content = "[1000]\nrxmixerset=600\ncustomdriveroption=kept\n\n[1001]\nrxmixerset=501\n"

    preview = client.post("/files/simpleusb.conf", data={"action": "preview", "content": content})
    assert preview.status_code == 200
    committed = client.post("/files/simpleusb.conf", data={
        "action": "commit", "confirmed": "yes", "content": content,
        "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
    })
    assert committed.status_code == 302

    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1000).one()
            assert node.simpleusb_settings.rxmixerset == 600
            custom = session.query(ConfigValue).filter_by(
                file_name="simpleusb.conf", section="1000", key="customdriveroption").one()
            assert custom.value == "kept"
    finally:
        _dispose(sessions, settings.database)


def test_advanced_usbradio_file_editor_saves_typed_and_unknown_fields(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    content = "[1000]\nrxdemod=speaker\nrxvoiceadj=0.625\ncustomdriveroption=kept\n"

    preview = client.post("/files/usbradio.conf", data={"action": "preview", "content": content})
    assert preview.status_code == 200
    committed = client.post("/files/usbradio.conf", data={
        "action": "commit", "confirmed": "yes", "content": content,
        "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
    })
    assert committed.status_code == 302

    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1000).one()
            assert node.usbradio_settings.rxdemod == "speaker"
            assert node.usbradio_settings.rxvoiceadj == "0.625"
            custom = session.query(ConfigValue).filter_by(
                file_name="usbradio.conf", section="1000", key="customdriveroption").one()
            assert custom.value == "kept"
    finally:
        _dispose(sessions, settings.database)


def test_editor_rejects_text_that_differs_from_preview(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    response = client.post("/files/rpt.conf", data={
        "action": "commit", "confirmed": "yes", "preview_hash": "hash-of-earlier-text",
        "content": "[1000]\nhangtime=1234\n",
    })
    assert response.status_code == 400


def test_iax_register_credentials_are_masked_and_preserved_on_save(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    sessions = session_factory(settings.database)
    try:
        with sessions.begin() as session:
            session.add(CustomLine(file_name="iax.conf", section="general", line_number=0,
                                   content="register => demo:secret@host.invalid"))
            session.add(CustomLine(file_name="iax.conf", section="general", line_number=1,
                                   content="register => demo:other@host.invalid"))
        _dispose(sessions, settings.database)
        page = client.get("/files/iax.conf")
        assert b"register =&gt; [hidden]" in page.data
        assert b"secret@host.invalid" not in page.data
        content = ("[general]\n; added comment\nregister => [hidden]\n\n"
                   "; comment between registrations\nregister => [hidden]\n")
        preview = client.post("/files/iax.conf", data={"action": "preview", "content": content})
        assert preview.status_code == 200
        saved = client.post("/files/iax.conf", data={
            "action": "commit", "confirmed": "yes", "content": content,
            "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
        })
        assert saved.status_code == 302
        generated = (settings.demo_output_directory / "iax.conf").read_text()
        assert "register => demo:secret@host.invalid" in generated
        assert "register => demo:other@host.invalid" in generated
        unresolved = "[general]\nregister => [hidden]\nregister => [hidden]\nregister => [hidden]\n"
        preview = client.post("/files/iax.conf", data={"action": "preview", "content": unresolved})
        assert preview.status_code == 200
        response = client.post("/files/iax.conf", data={
            "action": "commit", "confirmed": "yes", "content": unresolved,
            "preview_hash": hashlib.sha256(unresolved.encode()).hexdigest(),
        })
        assert response.status_code == 400
    finally:
        _dispose(sessions, settings.database)


def test_login_ignores_external_redirect_and_rejects_oversized_node_number(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    login = client.post("/login?next=https://example.invalid/", follow_redirects=False)
    assert login.headers["Location"] == "/"
    response = client.post("/nodes", data={"node_number": "9223372036854775808", "name": "Too large"})
    assert response.status_code == 400


def test_network_selection_setting_saves_true_value_and_readonly_page_is_safe(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated",
                        network_profiles_enabled=True)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    assert b"Download backup" not in client.get("/").data
    assert b"Network profiles" in client.get("/").data
    assert client.get("/networks").status_code == 200
    settings_page = client.get("/settings")
    assert b"networks.default_network" in settings_page.data
    assert b"network_profiles_enabled" not in settings_page.data
    assert client.post("/settings", data={"network_profiles_enabled": "false"}).status_code == 405
    assert b'name="network_id"' not in client.get("/networks").data
    assert client.post("/settings/default-network", data={"network_id": "1"}).status_code == 404
    enabled = client.post("/settings/network-selection", data={"enabled": "true"})
    assert enabled.status_code == 302
    assert b"Advanced per-node network selection" in client.get("/networks").data
    assert b'name="network_id"' in client.get("/networks").data
    assert client.post("/settings/default-network", data={"network_id": "1"}).status_code == 302
    assert b"Network profiles" in client.get("/").data
    assert b"Download backup" not in client.get("/").data

    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            assert session.get(Setting, "advanced_node_networks").value == "true"
            assert session.get(Setting, "default_network_key").value == "allstarlink"
        with sessions.begin() as session:
            session.add(Node(node_number=9044, name="Read-only target"))
        _dispose(sessions, settings.database)
        with client.session_transaction() as browser_session:
            browser_session["username"] = "reader"
        page = client.get("/")
        assert page.status_code == 200
        assert b"Read-only target" in page.data
        assert b"Download backup" not in page.data
        assert b"assign_network" not in page.data
    finally:
        _dispose(sessions, settings.database)


def test_backup_restore_has_its_own_menu_page(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    assert b"Backup &amp; Restore" in client.get("/").data
    assert b"Download backup" not in client.get("/").data
    page = client.get("/backup-restore")
    assert page.status_code == 200
    assert b"Download backup" in page.data
    assert b"Restore database" in page.data


def test_demo_settings_choose_an_isolated_database_and_explicit_config_must_exist(monkeypatch, tmp_path):
    from asterisk_node_manager.config import load_settings
    monkeypatch.setenv("ASTNODE_WEB__DEMO_MODE", "yes")
    monkeypatch.delenv("ASTNODE_PATHS__DATABASE", raising=False)
    monkeypatch.delenv("ASTNODE_CONFIG", raising=False)
    settings = load_settings()
    assert settings.demo_mode is True
    assert settings.database == ":memory:"

    configured_database = tmp_path / "production.sqlite3"
    config = tmp_path / "demo.toml"
    config.write_text(f'[paths]\ndatabase = "{configured_database}"\n')
    monkeypatch.setenv("ASTNODE_PATHS__DATABASE", str(configured_database))
    assert load_settings(config).database == ":memory:"
    assert not configured_database.exists()
    from asterisk_node_manager.config import Settings
    for database_path in (Settings.database, configured_database):
        with pytest.raises(ValueError, match="in-memory database"):
            create_app(Settings(database=database_path, demo_mode=True,
                                secret_key_file=tmp_path / "missing-secret"))

    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing-explicit-config.toml")


def test_web_main_logs_mode_and_listen_address(monkeypatch, caplog):
    import logging
    from asterisk_node_manager import web

    settings = Settings(database=":memory:", demo_mode=True, listen_address="127.0.0.1", port=8765)
    monkeypatch.setattr(web, "load_settings", lambda: settings)
    monkeypatch.setattr(web, "create_app", lambda _settings: object())
    monkeypatch.setattr(web, "serve", lambda _app, **_kwargs: None)

    with caplog.at_level(logging.INFO):
        assert web.main() == 0

    assert "Starting node-manager web service in demo mode" in caplog.text
    assert "Listening on http://127.0.0.1:8765" in caplog.text
