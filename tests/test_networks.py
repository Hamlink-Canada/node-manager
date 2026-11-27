import json

from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.migrate import upgrade_database
from asterisk_node_manager.models import Network
from asterisk_node_manager.networks import load_network_profiles, parse_network_profile
from asterisk_node_manager.web import create_app


def profile(key, name, **overrides):
    values = {
        "schema_version": 2,
        "key": key,
        "name": name,
        "registration_method": "http",
        "http_registration_server": "",
        "iax_registration_server": "",
        "iax_registration_port": 4569,
        "stats_enabled": False,
        "stats_post_url": "",
        "stats_post_interval": 60,
        "node_lookup_method": "both",
        "dns_node_domain": "",
        "max_dns_node_length": 6,
        "external_node_file": "",
    }
    values.update(overrides)
    return values


def test_network_profile_requires_explicit_registration_stats_and_lookup_fields():
    value = profile("example.net", "Example Network", registration_method="iax",
                    iax_registration_server="register.example.net", stats_enabled=True,
                    stats_post_url="https://stats.example.net/update",
                    node_lookup_method="dns", dns_node_domain="nodes.example.net")
    parsed = parse_network_profile(value)
    assert parsed["registration_method"] == "iax"
    assert parsed["stats_post_url"] == "https://stats.example.net/update"
    assert parsed["node_lookup_method"] == "dns"
    assert "config" not in parsed

    with_opaque_blob = {**value, "config": {"endpoint": "legacy.invalid"}}
    try:
        parse_network_profile(with_opaque_blob)
    except ValueError as exc:
        assert "schema" in str(exc).lower()
    else:
        raise AssertionError("opaque profile config should be rejected")


def test_network_profile_rejects_unsafe_hosts_and_stats_urls():
    invalid = profile("example.net", "Example", http_registration_server="host.example\nregister=no")
    try:
        parse_network_profile(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("registration host with a newline should be rejected")

    invalid = profile("example.net", "Example", stats_enabled=True,
                      stats_post_url="https://stats.example.net/update\nregister=no")
    try:
        parse_network_profile(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("stats URL with a newline should be rejected")


def test_startup_profile_scan_inserts_and_updates_by_key_and_skips_invalid(tmp_path):
    database = tmp_path / "manager.sqlite3"
    directory = tmp_path / "networks"
    directory.mkdir()
    upgrade_database(database)
    (directory / "new-network.json").write_text(json.dumps(profile(
        "example.net", "Example Network", http_registration_server="register.example.net",
        dns_node_domain="nodes.example.net", node_lookup_method="dns")))
    (directory / "allstarlink.json").write_text(json.dumps(profile(
        "allstarlink", "Updated AllStarLink", http_registration_server="updated.invalid")))
    (directory / "invalid.json").write_text("not-json")

    assert load_network_profiles(directory, database) == 2
    sessions = session_factory(database)
    try:
        with sessions() as db:
            assert db.query(Network).count() == 2
            example = db.query(Network).filter_by(stable_key="example.net").one()
            assert example.http_registration_server == "register.example.net"
            assert example.dns_node_domain == "nodes.example.net"
            allstar = db.query(Network).filter_by(stable_key="allstarlink").one()
            assert allstar.name == "Updated AllStarLink"
            assert allstar.http_registration_server == "updated.invalid"
        (directory / "new-network.json").write_text(json.dumps(profile(
            "example.net", "Renamed Network", stats_enabled=True,
            stats_post_url="https://stats.example.net/update")))
        assert load_network_profiles(directory, database) == 2
        with sessions() as db:
            network = db.query(Network).filter_by(stable_key="example.net").one()
            assert network.name == "Renamed Network"
            assert network.stats_enabled is True
            assert network.stats_post_url == "https://stats.example.net/update"
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
    (directory / "operator-network.json").write_text(json.dumps(profile(
        "operator.example", "Operator Network", iax_registration_server="radio.example.invalid",
        registration_method="iax", iax_registration_port=4570)))
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
            assert network.registration_method == "iax"
            assert network.iax_registration_port == 4570
    finally:
        sessions.kw["bind"].dispose()
