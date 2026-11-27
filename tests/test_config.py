from pathlib import Path

import pytest

from asterisk_node_manager.config import load_settings


def test_settings_load_toml_and_environment_overrides(monkeypatch, tmp_path):
    config = tmp_path / "node-manager.toml"
    config.write_text('''[paths]\ndatabase = "./db.sqlite3"\nasterisk_directory = "./etc-asterisk"\n\n[web]\nlisten_address = "0.0.0.0"\nport = 9000\ndemo_mode = true\n''')
    monkeypatch.setenv("ASTNODE_WEB__PORT", "9876")

    settings = load_settings(config)
    assert settings.database == ":memory:"
    assert settings.network_profiles_directory == Path("/etc/asterisk-node-manager/networks")
    assert settings.asterisk_directory == Path("./etc-asterisk")
    assert settings.listen_address == "0.0.0.0"
    assert settings.port == 9876
    assert settings.demo_mode is True


def test_explicit_missing_config_is_an_error(monkeypatch, tmp_path):
    missing = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError, match="Configuration file not found"):
        load_settings(missing)
    monkeypatch.setenv("ASTNODE_CONFIG", str(missing))
    with pytest.raises(FileNotFoundError, match="Configuration file not found"):
        load_settings()


def test_dynaconf_nested_environment_overrides_toml(monkeypatch, tmp_path):
    config = tmp_path / "node-manager.toml"
    config.write_text('''[paths]\ndatabase = "./from-file.sqlite3"\n
[web]
listen_address = "127.0.0.1"
port = 8765
''', encoding="utf-8")
    monkeypatch.setenv("ASTNODE_PATHS__DATABASE", "./from-env.sqlite3")
    monkeypatch.setenv("ASTNODE_WEB__PORT", "9010")

    settings = load_settings(config)

    assert settings.database == Path("from-env.sqlite3")
    assert settings.port == 9010


@pytest.mark.parametrize("value", ["invalid", "0", "65536"])
def test_invalid_dynaconf_port_is_rejected(monkeypatch, tmp_path, value):
    config = tmp_path / "optional.toml"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("ASTNODE_WEB__PORT", value)
    with pytest.raises(ValueError, match="web.port"):
        load_settings(config)
