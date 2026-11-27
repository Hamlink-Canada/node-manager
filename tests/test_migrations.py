from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

import asterisk_node_manager
from asterisk_node_manager.migrate import upgrade_database


def _alembic_config(database):
    package_dir = Path(asterisk_node_manager.__file__).parent
    config = Config(f"{package_dir}/alembic.ini")
    config.set_main_option("script_location", f"{package_dir}/migrations")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_migration_history_is_one_fresh_install_revision():
    config = _alembic_config("/tmp/unused-node-manager-test.sqlite3")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0001_initial_schema"]
    assert [revision.revision for revision in scripts.walk_revisions()] == ["0001_initial_schema"]


def test_initial_migration_creates_current_schema_from_empty_database(tmp_path):
    database = tmp_path / "fresh.sqlite3"
    command.upgrade(_alembic_config(database), "head")
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)

    assert {"settings", "networks", "nodes", "simpleusb_settings", "usbradio_settings",
            "config_values", "custom_values", "custom_lines", "module_directives",
            "extension_rules", "changes", "generated_files"} <= set(
                inspector.get_table_names())
    config_value_columns = {column["name"] for column in inspector.get_columns("config_values")}
    assert {"default_value", "updated_value"} <= config_value_columns
    assert "is_default" in {column["name"] for column in inspector.get_columns("custom_lines")}
    module_columns = {column["name"] for column in inspector.get_columns("module_directives")}
    assert {"module", "action", "is_default", "is_custom", "updated_action"} <= module_columns
    extension_columns = {column["name"] for column in inspector.get_columns("extension_rules")}
    assert {"context", "directive", "extension", "priority", "application", "arguments",
            "is_default", "is_custom", "updated_application", "updated_arguments"} <= extension_columns
    node_columns = {column["name"] for column in inspector.get_columns("nodes")}
    assert {"rxchannel", "duplex", "linktolink", "hangtime", "callerid"} <= node_columns
    assert "settings" not in node_columns
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
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_initial_schema"
    engine.dispose()


def test_fresh_database_seeds_declared_configuration_defaults(tmp_path):
    database = tmp_path / "seeded.sqlite3"
    upgrade_database(database)
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM config_values")).scalar_one() > 0
        assert connection.execute(text("SELECT count(*) FROM custom_lines WHERE is_default=1")).scalar_one() > 0
        assert connection.execute(text("SELECT count(*) FROM module_directives WHERE is_default=1")).scalar_one() > 0
        assert connection.execute(text("SELECT count(*) FROM extension_rules WHERE is_default=1")).scalar_one() > 0
        assert connection.execute(text("SELECT stable_key FROM networks")).scalars().all() == ["allstarlink"]
    engine.dispose()
