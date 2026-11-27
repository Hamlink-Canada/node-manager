from asterisk_node_manager import cli
from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.models import Node
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
