import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

import asterisk_node_manager
from asterisk_node_manager.migrate import upgrade_database
from asterisk_node_manager.models import Network, Node, SimpleUSBSettings, USBRadioSettings
from asterisk_node_manager.database import session_factory


def _alembic_config(database):
    package_dir = Path(asterisk_node_manager.__file__).parent
    config = Config(f"{package_dir}/alembic.ini")
    config.set_main_option("script_location", f"{package_dir}/migrations")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_migration_graph_has_one_head():
    config = _alembic_config("/tmp/unused-node-manager-test.sqlite3")
    assert ScriptDirectory.from_config(config).get_heads() == ["0006_explicit_network_settings"]


def test_fresh_database_has_typed_settings_and_only_allstarlink_network(tmp_path):
    database = tmp_path / "fresh.sqlite3"
    upgrade_database(database)
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    node_columns = {column["name"] for column in inspector.get_columns("nodes")}
    assert {"rxchannel", "duplex", "linktolink", "hangtime", "callerid"} <= node_columns
    assert "settings" not in node_columns
    assert {column["name"] for column in inspector.get_columns("simpleusb_settings")} >= {
        "rxboost", "carrierfrom", "rxmixerset", "txmixaset", "txmixbset"
    }
    assert {column["name"] for column in inspector.get_columns("usbradio_settings")} >= {
        "rxboost", "carrierfrom", "rxdemod", "rxvoiceadj", "rxctcssfreqs", "txmixaset"
    }
    network_columns = {column["name"] for column in inspector.get_columns("networks")}
    assert {"registration_method", "http_registration_server", "iax_registration_server",
            "stats_enabled", "stats_post_url", "node_lookup_method", "dns_node_domain"} <= network_columns
    assert "config" not in network_columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT stable_key FROM networks")).scalars().all() == ["allstarlink"]
        allstar = connection.execute(text(
            "SELECT registration_method, http_registration_server, stats_post_url, "
            "node_lookup_method, dns_node_domain FROM networks WHERE stable_key='allstarlink'"
        )).one()
        assert allstar == ("http", "register.allstarlink.org",
                           "http://stats.allstarlink.org/uhandler", "dns", "nodes.allstarlink.org")
        assert connection.execute(text(
            "SELECT count(*) FROM settings WHERE key='network_profiles_enabled'")).scalar_one() == 0
        assert connection.execute(text(
            "SELECT count(*) FROM settings WHERE key='default_network_key'")).scalar_one() == 0
    engine.dispose()


def test_migration_moves_legacy_settings_into_typed_columns(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    config = _alembic_config(database)
    command.upgrade(config, "0002_change_details")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO nodes (node_number, name, network_id, enabled, settings) "
                                "VALUES (1234, 'Imported node', NULL, 1, :settings)"),
                           {"settings": json.dumps({"rxchannel": "SimpleUSB/1234", "duplex": "0",
                                                    "hangtime": "2345", "linktolink": "yes",
                                                    "oldcustom": "legacy", "custompassword": "keep-me"})})
        connection.execute(text("INSERT INTO config_values (file_name, section, key, value, secret) "
                                "VALUES ('simpleusb.conf', '1234', 'rxmixerset', '612', 0)"))
        connection.execute(text("INSERT INTO config_values (file_name, section, key, value, secret) "
                                "VALUES ('rpt.conf', '1234', 'oldcustom', 'existing', 0)"))
    engine.dispose()

    upgrade_database(database)
    sessions = session_factory(database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1234).one()
            assert node.rxchannel == "SimpleUSB/1234"
            assert node.duplex == 0
            assert node.hangtime == 2345
            assert node.linktolink is True
            assert node.simpleusb_settings.rxmixerset == 612
            assert node.usbradio_settings is not None
            assert session.query(USBRadioSettings).count() == 1
            assert session.query(Network).count() == 1
            assert session.query(SimpleUSBSettings).count() == 1
            retained = session.execute(text(
                "SELECT value FROM config_values WHERE file_name='rpt.conf' AND key='oldcustom'"
            )).scalar_one()
            assert retained == "existing"
            secret, secret_flag = session.execute(text(
                "SELECT value, secret FROM config_values WHERE file_name='rpt.conf' AND key='custompassword'"
            )).one()
            assert secret == "keep-me"
            assert secret_flag is True or secret_flag == 1
    finally:
        sessions.kw["bind"].dispose()


def test_network_migration_moves_recognized_profile_values_into_columns(tmp_path):
    database = tmp_path / "network-fields.sqlite3"
    config = _alembic_config(database)
    command.upgrade(config, "0005_usbradio_settings")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO networks (stable_key, name, schema_version, config) "
            "VALUES ('example.net', 'Example Network', 1, :config)"),
            {"config": json.dumps({
                "registration_method": "iax", "iax_registration_server": "register.example.net",
                "iax_registration_port": 4570, "stats_enabled": True,
                "stats_post_url": "https://stats.example.net/update",
                "node_lookup_method": "dns", "dns_node_domain": "nodes.example.net",
                "max_dns_node_length": 8, "unrecognized": "discarded",
            })})
    engine.dispose()

    upgrade_database(database)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            values = connection.execute(text(
                "SELECT schema_version, registration_method, iax_registration_server, "
                "iax_registration_port, stats_enabled, stats_post_url, node_lookup_method, "
                "dns_node_domain, max_dns_node_length FROM networks WHERE stable_key='example.net'"
            )).one()
            assert values == (2, "iax", "register.example.net", 4570, 1,
                              "https://stats.example.net/update", "dns", "nodes.example.net", 8)
            assert "config" not in {column["name"] for column in inspect(connection).get_columns("networks")}
    finally:
        engine.dispose()
