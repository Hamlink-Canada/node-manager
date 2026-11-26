Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
from asterisk_node_manager.generate import render_database
from asterisk_node_manager.models import ConfigValue, Node, SimpleUSBSettings


def test_generation_renders_typed_node_and_simpleusb_settings(database):
    sessions = __import__("asterisk_node_manager.database", fromlist=["session_factory"]).session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="Test node", rxchannel="SimpleUSB/4321", duplex=0,
                             hangtime=3456, linktolink=True,
                             simpleusb_settings=SimpleUSBSettings(rxmixerset=644, rxboost=True)))
            session.add(ConfigValue(file_name="rpt.conf", section="4321", key="customadvanced",
                                    value="preserved", secret=False))
        files = render_database(database)
    finally:
        sessions.kw["bind"].dispose()

    rpt = files["rpt.conf"].decode()
    simpleusb = files["simpleusb.conf"].decode()
    assert "[4321]" in rpt
    assert "rxchannel = SimpleUSB/4321" in rpt
    assert "duplex = 0" in rpt
    assert "hangtime = 3456" in rpt
    assert "linktolink = yes" in rpt
    assert "customadvanced = preserved" in rpt
    assert "rxmixerset = 644" in simpleusb
    assert "rxboost = yes" in simpleusb
    assert "rxmixerset = 500" not in simpleusb
