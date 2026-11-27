from asterisk_node_manager import cli
from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.configuration import node_config_values
from asterisk_node_manager.models import Node
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
