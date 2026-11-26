from asterisk_node_manager import cli
from asterisk_node_manager.config import Settings
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.models import Node


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
