from asterisk_node_manager.asterisk_config import parse_config
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.generate import render_database
from asterisk_node_manager.models import (
    ConfigValue,
    CustomLine,
    Node,
    SimpleUSBSettings,
)


def test_generation_renders_typed_node_and_simpleusb_settings(database):
    sessions = session_factory(database)
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


def test_inheritance_suffixes_survive_import_and_render(database):
    sessions = session_factory(database)
    source = "[alpha](zbase)\nexten => 100,1,Answer()\n\n[zbase](!)\npriorityjumping=no\n"
    values, lines = parse_config("extensions.conf", source)
    try:
        with sessions.begin() as session:
            for section, entries in values.items():
                for key, value in entries.items():
                    session.add(ConfigValue(file_name="extensions.conf", section=section,
                                            key=key, value=value, secret=False))
            for section, entries in lines.items():
                for index, line in enumerate(entries):
                    session.add(CustomLine(file_name="extensions.conf", section=section,
                                           line_number=index, content=line))
        rendered = render_database(database)["extensions.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "[alpha](zbase)" in rendered
    assert "[zbase](!)" in rendered
    assert "[alpha(zbase)]" not in rendered
    assert rendered.index("[zbase](!)") < rendered.index("[alpha](zbase)")


def test_rpt_global_include_precedes_parent_and_custom_only_sections(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add_all([
                CustomLine(file_name="rpt.conf", section="", line_number=0,
                           content='#include "rpt-templates.conf"'),
                CustomLine(file_name="rpt.conf", section="alpha(zbase)", line_number=0,
                           content="functions = 1"),
                CustomLine(file_name="rpt.conf", section="zbase(!)", line_number=0,
                           content="duplex = 0"),
            ])
        rendered = render_database(database)["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert rendered.index('#include "rpt-templates.conf"') < rendered.index("[zbase](!)")
    assert rendered.index("[zbase](!)") < rendered.index("[alpha](zbase)")
    assert "functions = 1" in rendered
    assert "duplex = 0" in rendered
