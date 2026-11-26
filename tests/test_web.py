Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
from io import BytesIO
import json

from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.migrate import upgrade_database
from asterisk_node_manager.models import ConfigValue, Network, Node
from asterisk_node_manager.web import create_app


def test_demo_mode_login_and_node_configuration_work_without_writer_socket(tmp_path):
    settings = Settings(database=tmp_path / "demo.sqlite3", demo_mode=True,
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
        saved = client.post(f"/nodes/{node_id}/configuration", data={
            "rxchannel": "SimpleUSB/1000", "duplex": "0", "hangtime": "5000",
            "linktolink": "yes", "advanced_view": "yes",
        })
        assert saved.status_code == 302
        generated_rpt = (settings.demo_output_directory / "rpt.conf").read_text()
        assert "linktolink = yes" in generated_rpt
        assert "duplex = 0" in generated_rpt
    finally:
        sessions.kw["bind"].dispose()


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
    assert client.post("/nodes", data={"node_number": "1200", "name": "Unauthorized"}).status_code == 403
    assert client.get("/backup").status_code == 403


def test_network_profile_upload_validates_and_updates_by_stable_key(tmp_path):
    settings = Settings(database=tmp_path / "networks.sqlite3", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    profile = {"schema_version": 1, "key": "example.net", "name": "Example network",
               "config": {"register": True, "server": "example.invalid"}}
    preview = client.post("/networks/import", data={
        "network": (BytesIO(json.dumps(profile).encode()), "example.json")
    }, content_type="multipart/form-data")
    assert preview.status_code == 200
    assert b"Example network" in preview.data

    committed = client.post("/networks/import", data={
        "action": "commit", "schema_version": "1", "key": "example.net",
        "name": "Example network", "config": json.dumps(profile["config"]),
    })
    assert committed.status_code == 302
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            original = session.query(Network).filter_by(stable_key="example.net").one()
            original_id = original.id

        replacement = client.post("/networks/import", data={
            "action": "commit", "schema_version": "1", "key": "example.net",
            "name": "Updated network", "config": json.dumps({"register": False}),
        })
        assert replacement.status_code == 302
        with sessions() as session:
            network = session.query(Network).filter_by(stable_key="example.net").one()
            assert network.id == original_id
            assert network.name == "Updated network"
            assert network.config == {"register": False}
            assert session.query(Network).filter_by(stable_key="allstarlink").count() == 1
    finally:
        sessions.kw["bind"].dispose()


def test_web_database_backup_and_restore_reverts_later_changes(tmp_path):
    settings = Settings(database=tmp_path / "backup.sqlite3", demo_mode=True,
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
        sessions.kw["bind"].dispose()
        restored = client.post("/restore", data={
            "database": (BytesIO(backup_bytes), "backup.sqlite3")
        }, content_type="multipart/form-data")
        assert restored.status_code == 302
        restored_sessions = session_factory(settings.database)
        with restored_sessions() as session:
            assert session.query(Node).filter_by(node_number=9090).count() == 0
            assert session.query(Node).filter_by(node_number=1000).count() == 1
        restored_sessions.kw["bind"].dispose()
    finally:
        sessions.kw["bind"].dispose()


def test_advanced_simpleusb_file_editor_saves_known_and_unknown_fields(tmp_path):
    settings = Settings(database=tmp_path / "editor.sqlite3", demo_mode=True,
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
        sessions.kw["bind"].dispose()
