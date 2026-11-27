import json

from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.migrate import upgrade_database
from asterisk_node_manager.models import Network
from asterisk_node_manager.networks import load_network_profiles
from asterisk_node_manager.web import create_app


def test_startup_profile_scan_inserts_and_updates_by_key_and_skips_invalid(tmp_path):
    database = tmp_path / "manager.sqlite3"
    directory = tmp_path / "networks"
    directory.mkdir()
    upgrade_database(database)
    (directory / "new-network.json").write_text(json.dumps({
        "schema_version": 1, "key": "example.net", "name": "Example Network",
        "config": {"endpoint": "example.invalid"},
    }))
    (directory / "allstarlink.json").write_text(json.dumps({
        "schema_version": 1, "key": "allstarlink", "name": "Updated AllStarLink",
        "config": {"endpoint": "updated.invalid"},
    }))
    (directory / "invalid.json").write_text("not-json")

    assert load_network_profiles(directory, database) == 2
    sessions = session_factory(database)
    try:
        with sessions() as db:
            assert db.query(Network).count() == 2
            assert db.query(Network).filter_by(stable_key="example.net").one().config == {
                "endpoint": "example.invalid"}
            allstar = db.query(Network).filter_by(stable_key="allstarlink").one()
            assert allstar.name == "Updated AllStarLink"
            assert allstar.config == {"endpoint": "updated.invalid"}
        (directory / "new-network.json").write_text(json.dumps({
            "schema_version": 1, "key": "example.net", "name": "Renamed Network",
            "config": {},
        }))
        assert load_network_profiles(directory, database) == 2
        with sessions() as db:
            network = db.query(Network).filter_by(stable_key="example.net").one()
            assert network.name == "Renamed Network"
    finally:
        sessions.kw["bind"].dispose()


def test_startup_profile_scan_ignores_missing_directory(tmp_path):
    database = tmp_path / "manager.sqlite3"
    upgrade_database(database)
    assert load_network_profiles(tmp_path / "absent", database) == 0


def test_web_startup_scans_the_configured_network_profile_directory(tmp_path):
    database = tmp_path / "manager.sqlite3"
    directory = tmp_path / "profiles"
    directory.mkdir()
    (directory / "operator-network.json").write_text(json.dumps({
        "schema_version": 1, "key": "operator.example", "name": "Operator Network",
        "config": {"endpoint": "radio.example.invalid"},
    }))
    upgrade_database(database)
    secret = tmp_path / "secret"
    secret.write_text("test-secret")

    create_app(Settings(database=database, secret_key_file=secret,
                       network_profiles_directory=directory))
    sessions = session_factory(database)
    try:
        with sessions() as db:
            network = db.query(Network).filter_by(stable_key="operator.example").one()
            assert network.name == "Operator Network"
    finally:
        sessions.kw["bind"].dispose()
