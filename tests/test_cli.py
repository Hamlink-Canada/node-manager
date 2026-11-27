from asterisk_node_manager import cli
from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.configuration import node_config_values
from asterisk_node_manager.models import CustomValue, Node
from asterisk_node_manager.generate import render_database
from asterisk_node_manager.migrate import upgrade_database
import sqlite3


def test_import_preview_does_not_create_database_or_change_files(tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "rpt.conf").write_text("[1234]\nrxchannel=SimpleUSB/1234\nduplex=0\n")
    settings = Settings(database=tmp_path / "manager.sqlite3", asterisk_directory=tmp_path / "asterisk")

    assert cli._import_config(source, False, settings) == 0
    assert not settings.database.exists()
    assert not settings.asterisk_directory.exists()


def test_import_commit_maps_known_fields_and_regenerates(monkeypatch, tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "rpt.conf").write_text(
        "[1234]\nrxchannel=SimpleUSB/1234\nduplex=0\nhangtime=2222\ncustomoption=kept\n"
    )
    (source / "simpleusb.conf").write_text("[1234]\nrxmixerset=632\nrxboost=yes\n")
    settings = Settings(database=tmp_path / "manager.sqlite3", asterisk_directory=tmp_path / "asterisk")
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("asterisk_node_manager.writer._replace_files", lambda *args: None)

    assert cli._import_config(source, True, settings) == 0
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1234).one()
            assert node.rxchannel == "SimpleUSB/1234"
            assert node.duplex == 0
            assert node.hangtime == 2222
            assert node.simpleusb_settings.rxmixerset == 632
            assert node.simpleusb_settings.rxboost is True
            assert session.query(Node).count() == 1
            assert session.query(CustomValue).filter_by(
                file_name="rpt.conf", section="1234", key="customoption").one().value == "kept"
        assert "customoption = kept" in render_database(settings.database)["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()


def test_import_node_overrides_compare_against_incoming_template_defaults(monkeypatch, tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "rpt.conf").write_text(
        "[node-main]\nhangtime=6000\n[1234](node-main)\nhangtime=5000\n"
    )
    settings = Settings(database=tmp_path / "manager.sqlite3", asterisk_directory=tmp_path / "asterisk")
    upgrade_database(settings.database)
    sessions = session_factory(settings.database)
    with sessions.begin() as session:
        from asterisk_node_manager.models import ConfigValue
        default = session.query(ConfigValue).filter_by(
            file_name="rpt.conf", section="node-main", key="hangtime").one()
        default.default_value = "5000"
    sessions.kw["bind"].dispose()
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("asterisk_node_manager.writer._replace_files", lambda *args: None)

    assert cli._import_config(source, True, settings) == 0
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1234).one()
            assert node.hangtime == 5000
    finally:
        sessions.kw["bind"].dispose()


def test_import_usbradio_without_rpt_section_selects_radio_and_renders(monkeypatch, tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "usbradio.conf").write_text("[1234]\nrxdemod=speaker\n")
    settings = Settings(database=tmp_path / "manager.sqlite3", asterisk_directory=tmp_path / "asterisk")
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("asterisk_node_manager.writer._replace_files", lambda *args: None)

    assert cli._import_config(source, True, settings) == 0
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1234).one()
            assert node.rxchannel == "Radio/1234"
            assert node.usbradio_settings.rxdemod == "speaker"
        assert "rxdemod = speaker" in render_database(settings.database)["usbradio.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()


def test_import_usbradio_preserves_explicit_local_channel(monkeypatch, tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "rpt.conf").write_text("[1234](node-main)\nrxchannel=Local/pseudo\n")
    (source / "usbradio.conf").write_text("[1234]\nrxdemod=speaker\n")
    settings = Settings(database=tmp_path / "manager.sqlite3", asterisk_directory=tmp_path / "asterisk")
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("asterisk_node_manager.writer._replace_files", lambda *args: None)

    assert cli._import_config(source, True, settings) == 0
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1234).one()
            assert node_config_values(node)["rxchannel"] == "Local/pseudo"
            assert node.usbradio_settings.rxdemod == "speaker"
    finally:
        sessions.kw["bind"].dispose()


def test_import_rejects_node_ids_with_fewer_than_four_digits(monkeypatch, tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "rpt.conf").write_text("[123]\nrxchannel=Local/pseudo\n")
    settings = Settings(database=tmp_path / "manager.sqlite3")
    monkeypatch.setattr(cli, "_require_root", lambda: None)

    assert cli._import_config(source, True, settings) == 2
    assert not settings.database.exists()


def test_imported_codec_directives_keep_source_order_when_regenerated(monkeypatch, tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "iax.conf").write_text(
        "[general]\nallow = all\ndisallow = all\nallow = ulaw\n"
    )
    settings = Settings(database=tmp_path / "manager.sqlite3", asterisk_directory=tmp_path / "asterisk")
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("asterisk_node_manager.writer._replace_files", lambda *args: None)

    assert cli._import_config(source, True, settings) == 0
    rendered = render_database(settings.database)["iax.conf"].decode().splitlines()
    section = ""
    codec_lines = []
    for line in rendered:
        if line.startswith("["):
            section = line
        elif section == "[general]" and line.strip().startswith(("allow =", "disallow =")):
            codec_lines.append(line.strip())
    assert codec_lines == ["allow = all", "disallow = all", "allow = ulaw"]


def test_import_preserves_asterisk_include_directives(monkeypatch, tmp_path):
    source = tmp_path / "existing"
    source.mkdir()
    (source / "iax.conf").write_text('[general]\n#include "extra.conf"\n#tryinclude "optional.conf"\n')
    settings = Settings(database=tmp_path / "manager.sqlite3", asterisk_directory=tmp_path / "asterisk")
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("asterisk_node_manager.writer._replace_files", lambda *args: None)

    assert cli._import_config(source, True, settings) == 0
    rendered = render_database(settings.database)["iax.conf"].decode()
    assert '#include "extra.conf"' in rendered
    assert '#tryinclude "optional.conf"' in rendered


def test_generated_node_configuration_imports_back_as_a_node(monkeypatch, tmp_path):
    source = tmp_path / "generated"
    source.mkdir()
    initial = Settings(database=tmp_path / "initial.sqlite3", asterisk_directory=tmp_path / "initial-asterisk")
    upgrade_database(initial.database)
    sessions = session_factory(initial.database)
    with sessions.begin() as session:
        session.add(Node(node_number=1234, name="Imported node", rxchannel="Radio/1234", duplex=0))
    (source / "rpt.conf").write_bytes(render_database(initial.database)["rpt.conf"])
    sessions.kw["bind"].dispose()

    restored = Settings(database=tmp_path / "restored.sqlite3", asterisk_directory=tmp_path / "restored-asterisk")
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("asterisk_node_manager.writer._replace_files", lambda *args: None)
    assert cli._import_config(source, True, restored) == 0
    restored_sessions = session_factory(restored.database)
    try:
        with restored_sessions() as session:
            node = session.query(Node).filter_by(node_number=1234).one()
            assert node_config_values(node)["rxchannel"] == "Radio/1234"
            assert node.duplex == 0
    finally:
        restored_sessions.kw["bind"].dispose()


def test_restore_rejects_unrelated_sqlite_database_without_replacing_current(monkeypatch, tmp_path):
    settings = Settings(database=tmp_path / "manager.sqlite3")
    upgrade_database(settings.database)
    sessions = session_factory(settings.database)
    with sessions.begin() as session:
        session.add(Node(node_number=1234, name="Existing node"))
    unrelated = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    monkeypatch.setattr(cli, "load_settings", lambda _path=None: settings)
    monkeypatch.setattr(cli, "_require_root", lambda: None)
    monkeypatch.setattr("sys.argv", ["astnode", "restore", str(unrelated)])

    assert cli.main() == 2
    with sessions() as session:
        assert session.query(Node).filter_by(node_number=1234).one().name == "Existing node"
