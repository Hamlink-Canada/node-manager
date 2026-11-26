from pathlib import Path
import pytest

from asterisk_node_manager.config import load_settings


def test_settings_load_toml_and_environment_overrides(monkeypatch, tmp_path):
    config = tmp_path / "node-manager.toml"
    config.write_text('''[paths]\ndatabase = "./db.sqlite3"\nasterisk_directory = "./etc-asterisk"\n\n[web]\nlisten_address = "0.0.0.0"\nport = 9000\ndemo_mode = true\n''')
    monkeypatch.delenv("ASTNODE_DATABASE", raising=False)
    monkeypatch.delenv("ASTNODE_LISTEN_ADDRESS", raising=False)
    monkeypatch.delenv("ASTNODE_DEMO", raising=False)
    monkeypatch.setenv("ASTNODE_PORT", "9876")

    settings = load_settings(config)
    assert settings.database == ":memory:"
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
