Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

import asterisk_node_manager
from asterisk_node_manager.migrate import upgrade_database
from asterisk_node_manager.models import Network, Node, SimpleUSBSettings
from asterisk_node_manager.database import session_factory


def _alembic_config(database):
    package_dir = Path(asterisk_node_manager.__file__).parent
    config = Config(f"{package_dir}/alembic.ini")
    config.set_main_option("script_location", f"{package_dir}/migrations")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_migration_graph_has_one_head():
    config = _alembic_config("/tmp/unused-node-manager-test.sqlite3")
    assert ScriptDirectory.from_config(config).get_heads() == ["0003_explicit_node_settings"]


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
    with engine.connect() as connection:
        assert connection.execute(text("SELECT stable_key FROM networks")).scalars().all() == ["allstarlink"]
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
                                                    "oldcustom": "retained"})})
        connection.execute(text("INSERT INTO config_values (file_name, section, key, value, secret) "
                                "VALUES ('simpleusb.conf', '1234', 'rxmixerset', '612', 0)"))
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
            assert session.query(Network).count() == 1
            assert session.query(SimpleUSBSettings).count() == 1
            retained = session.execute(text(
                "SELECT value FROM config_values WHERE file_name='rpt.conf' AND key='oldcustom'"
            )).scalar_one()
            assert retained == "retained"
    finally:
        sessions.kw["bind"].dispose()
