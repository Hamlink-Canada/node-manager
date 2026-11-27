from pathlib import Path

from asterisk_node_manager.asterisk_config import parse_config
from asterisk_node_manager.database import session_factory
from asterisk_node_manager.generate import GENERATED_FILES, render_database
from asterisk_node_manager.structured_config import save_structured_lines
from asterisk_node_manager.models import (
    ConfigValue,
    CustomLine,
    CustomValue,
    ExtensionRule,
    ModuleDirective,
    Network,
    Node,
    SimpleUSBSettings,
    USBRadioSettings,
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


def test_generation_renders_typed_usbradio_settings_only_for_radio_nodes(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="Radio node", rxchannel="Radio/4321",
                             usbradio_settings=USBRadioSettings(rxboost=False, rxvoiceadj="0.625")))
            session.add(Node(node_number=4322, name="Local node", rxchannel="Local/pseudo",
                             usbradio_settings=USBRadioSettings(rxboost=False)))
        files = render_database(database)
    finally:
        sessions.kw["bind"].dispose()

    radio = files["usbradio.conf"].decode()
    assert "[4321]" in radio
    assert "rxboost = no" in radio
    assert "rxvoiceadj = 0.625" in radio
    assert "[4322]" not in radio


def test_generation_uses_explicit_network_lookup_and_stats_settings(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            network = Network(
                stable_key="example.net", name="Example", schema_version=2,
                registration_method="http", http_registration_server="register.example.net",
                iax_registration_server="", iax_registration_port=4569,
                stats_enabled=True, stats_post_url="https://stats.example.net/update",
                stats_post_interval=90, node_lookup_method="dns",
                dns_node_domain="nodes.example.net", max_dns_node_length=8,
                external_node_file="/var/lib/asterisk/custom-nodes",
            )
            session.add(network)
            session.add(Node(node_number=4321, name="Network node", rxchannel="Local/pseudo"))
        rendered = render_database(database, default_network="example.net")["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "node_lookup_method = dns" in rendered
    assert "dns_node_domain = nodes.example.net" in rendered
    assert "max_dns_node_length = 8" in rendered
    assert "statpost_url = https://stats.example.net/update" in rendered
    assert "statpost_time = 90" in rendered


def test_generation_routes_registration_credentials_through_selected_profile(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            network = Network(
                stable_key="example.net", name="Example", schema_version=2,
                registration_method="http", http_registration_server="register.example.net",
                iax_registration_server="", iax_registration_port=4569,
                stats_enabled=False, stats_post_url="", stats_post_interval=60,
                node_lookup_method="both", dns_node_domain="", max_dns_node_length=6,
                external_node_file="",
            )
            session.add(network)
            session.add(Node(node_number=4321, name="Network node", rxchannel="Local/pseudo"))
            session.add(CustomLine(file_name="iax.conf", section="general", line_number=0,
                                   content="register => 4321:keepsecret@old.example.net"))
        files = render_database(database, default_network="example.net")
    finally:
        sessions.kw["bind"].dispose()

    assert "register => 4321:keepsecret@register.example.net" in files[
        "rpt_http_registrations.conf"].decode()
    assert "register => 4321:keepsecret@old.example.net" not in files["iax.conf"].decode()


def test_generation_uses_iax_profile_server_and_port_for_registration(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            network = session.query(Network).filter_by(stable_key="allstarlink").one()
            network.registration_method = "iax"
            network.iax_registration_server = "iax.example.net"
            network.iax_registration_port = 4570
            session.add(Node(node_number=4321, name="Network node", rxchannel="Local/pseudo"))
            session.add(CustomLine(file_name="rpt_http_registrations.conf", section="registrations",
                                   line_number=0,
                                   content="register => 4321:keepsecret@old.example.net"))
        files = render_database(database)
    finally:
        sessions.kw["bind"].dispose()

    assert "register => 4321:keepsecret@iax.example.net:4570" in files["iax.conf"].decode()
    assert "register => 4321:keepsecret@old.example.net" not in files[
        "rpt_http_registrations.conf"].decode()


def test_network_registration_accepts_equals_separator(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            network = session.query(Network).filter_by(stable_key="allstarlink").one()
            network.registration_method = "http"
            network.http_registration_server = "register.example.net"
            session.add(Node(node_number=4321, name="Network node", rxchannel="Local/pseudo"))
            session.add(CustomLine(file_name="iax.conf", section="general", line_number=0,
                                   content="register = 4321:keepsecret@old.example.net"))
        files = render_database(database)
    finally:
        sessions.kw["bind"].dispose()

    assert "register => 4321:keepsecret@register.example.net" in files[
        "rpt_http_registrations.conf"].decode()
    assert "register = 4321:keepsecret@old.example.net" not in files["iax.conf"].decode()


def test_unknown_default_network_preserves_registration(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="Network node", rxchannel="Local/pseudo"))
            session.add(CustomLine(file_name="iax.conf", section="general", line_number=0,
                                   content="register => 4321:keepsecret@old.example.net"))
        files = render_database(database, default_network="misspelled-network")
    finally:
        sessions.kw["bind"].dispose()

    assert "register => 4321:keepsecret@old.example.net" in files["iax.conf"].decode()


def test_echolink_module_override_replaces_the_default_noload(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            directive = session.query(ModuleDirective).filter_by(module="chan_echolink.so").one()
            directive.updated_action = "load"
            directive.is_custom = True
        lines = render_database(database)["modules.conf"].decode().splitlines()
    finally:
        sessions.kw["bind"].dispose()

    echolink_lines = [line.strip() for line in lines if "chan_echolink.so" in line]
    assert echolink_lines == ["load => chan_echolink.so"]


def test_disabled_profile_status_removes_imported_status_values(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="Network node", rxchannel="Local/pseudo"))
            session.add_all([
                ConfigValue(file_name="rpt.conf", section="4321", key="statpost_url",
                            value="https://old.example.net", secret=False),
                ConfigValue(file_name="rpt.conf", section="4321", key="statpost_time",
                            value="30", secret=False),
            ])
        rendered = render_database(database)["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "\nstatpost_url =" not in rendered
    assert "\nstatpost_time =" not in rendered


def test_generation_includes_complete_base_files_and_echolink(database):
    files = render_database(database)
    expected_sections = {
        "rpt.conf": ("[general]", "[functions]", "[telemetry]", "[controlstates]"),
        "iax.conf": ("[general]", "[radio]", "[iaxrpt]"),
        "extensions.conf": ("[globals]", "[radio]", "[radio-secure]"),
        "modules.conf": ("[modules]",),
        "manager.conf": ("[general]",),
        "echolink.conf": ("[el0]",),
        "simpleusb.conf": ("[general]",),
        "usbradio.conf": ("[general]",),
        "voter.conf": ("[general]",),
        "rpt_http_registrations.conf": ("[general]", "[registrations]"),
    }
    assert set(files) == set(GENERATED_FILES)
    for filename, sections in expected_sections.items():
        rendered = files[filename].decode()
        assert rendered.strip()
        assert all(section in rendered for section in sections), filename
        assert not any(line.lstrip().startswith(";") for line in rendered.splitlines()), filename
        assert not any(line.lstrip().startswith("#") and not line.lstrip().lower().startswith(
            ("#include", "#tryinclude")) for line in rendered.splitlines()), filename
        assert "[node-main](!)" not in rendered, filename
    assert "call =" in files["echolink.conf"].decode()
    assert "PASSWORD=12345" not in files["savenode.conf"].decode()
    assert "secret_password" not in files["voter.conf"].decode()
    assert "abcdef@register.allstarlink.org" not in files["rpt_http_registrations.conf"].decode()
    generated_text = "\n".join(data.decode() for data in files.values())
    assert "api.allstarlink.org" not in generated_text
    assert "register.allstarlink.org" not in generated_text
    assert "nodes.allstarlink.org" not in generated_text
    assert "stats.allstarlink.org" not in generated_text
    template_dir = Path(__file__).parents[1] / "src/asterisk_node_manager/conf"
    assert all((template_dir / f"{filename}.j2").is_file() for filename in GENERATED_FILES)


def test_database_config_values_override_packaged_baseline(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            bindport = session.query(ConfigValue).filter_by(
                file_name="iax.conf", section="general", key="bindport").one()
            bindport.value = "4570"
            echo_call = session.query(ConfigValue).filter_by(
                file_name="echolink.conf", section="el0", key="call").one()
            echo_call.value = "N0CALL-L"
        files = render_database(database)
    finally:
        sessions.kw["bind"].dispose()

    iax = files["iax.conf"].decode()
    assert "bindport = 4570" in iax
    assert "bindport = 4569" not in iax
    assert "call = N0CALL-L" in files["echolink.conf"].decode()


def test_defaults_and_updates_are_stored_separately_and_custom_values_overlay(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            default = session.query(ConfigValue).filter_by(
                file_name="iax.conf", section="general", key="bindport").one()
            assert default.default_value == "4569"
            default.value = "4571"
            session.add(CustomValue(file_name="iax.conf", section="general", key="bindport",
                                    value="4572", secret=False))
        rendered = render_database(database)["iax.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "bindport = 4572" in rendered
    assert "bindport = 4571" not in rendered
    assert "bindport = 4569" not in rendered


def test_asterisk_section_inheritance_is_expanded_without_emitting_templates(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add_all([
                ConfigValue(file_name="iax.conf", section="9000(!)", key="type",
                            default_value="user", secret=False),
                ConfigValue(file_name="iax.conf", section="9001(9000)", key="host",
                            default_value="dynamic", secret=False),
            ])
        rendered = render_database(database)["iax.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "[9001]" in rendered
    assert "type = user" in rendered
    assert "host = dynamic" in rendered
    assert "[9000](!)" not in rendered


def test_rpt_node_templates_expand_into_managed_node_sections(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="Inherited node"))
            session.add_all([
                ConfigValue(file_name="rpt.conf", section="9000(!)", key="customsetting",
                            default_value="template", secret=False),
                ConfigValue(file_name="rpt.conf", section="4321(9000)", key="customsetting",
                            default_value="node override", secret=False),
            ])
        rendered = render_database(database)["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "[4321]" in rendered
    assert "customsetting = node override" in rendered


def test_rpt_node_main_defaults_survive_inheritance_expansion(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="Inherited node"))
            session.add(CustomValue(file_name="rpt.conf", section="node-main(!)",
                                    key="functions", value="shared-functions", secret=False))
            session.add(CustomValue(file_name="rpt.conf", section="4321(node-main)",
                                    key="customsetting", value="child", secret=False))
        rendered = render_database(database)["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "functions = shared-functions" in rendered
    assert "customsetting = child" in rendered


def test_simpleusb_custom_node_main_default_is_used_for_unset_typed_field(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="USB node", rxchannel="SimpleUSB/4321",
                             simpleusb_settings=SimpleUSBSettings()))
            session.add(ConfigValue(file_name="simpleusb.conf", section="node-main",
                                    key="rxmixerset", default_value="500", secret=False))
            session.add(CustomValue(file_name="simpleusb.conf", section="node-main",
                                    key="rxmixerset", value="700", secret=False))
        rendered = render_database(database)["simpleusb.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert "rxmixerset = 700" in rendered
    assert "rxmixerset = 500" not in rendered


def test_rpt_node_custom_values_do_not_emit_duplicate_node_section_headers(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=4321, name="Configured node"))
            session.add(CustomValue(file_name="rpt.conf", section="4321", key="customsetting",
                                    value="retained", secret=False))
        rendered = render_database(database)["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert rendered.count("[4321]") == 1
    assert "customsetting = retained" in rendered


def test_unreferenced_numeric_rpt_template_sections_keep_values_and_lines(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add(ConfigValue(file_name="rpt.conf", section="9000(!)", key="customsetting",
                                    default_value="retained", secret=False))
            session.add(CustomLine(file_name="rpt.conf", section="9000(!)", line_number=0,
                                   content="customline => retained"))
        rendered = render_database(database)["rpt.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    assert rendered.count("[9000]") == 1
    assert "customsetting = retained" in rendered
    assert "customline => retained" in rendered


def test_extension_rule_import_preserves_reordered_positions(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            defaults = [
                ExtensionRule(context="review-fixture", line_number=0, directive="exten",
                              extension="s", priority="1", application="Answer",
                              is_default=True),
                ExtensionRule(context="review-fixture", line_number=1, directive="same",
                              extension=None, priority="n", application="Hangup",
                              is_default=True),
            ]
            session.add_all(defaults)
            original = [rule.render() for rule in defaults]
            reordered = list(reversed(original))
            save_structured_lines(session, "extensions.conf", {"review-fixture": reordered},
                                  replace_defaults=False)
        rendered = render_database(database)["extensions.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    positions = [rendered.index(rule) for rule in reordered]
    assert positions == sorted(positions)
    assert rendered.index(reordered[0]) < rendered.index(reordered[1])
    assert "[9000](!)" not in rendered
    assert "[9000]" not in rendered


def test_channel_driver_modules_follow_node_interfaces(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            session.add_all([
                Node(node_number=4321, name="SimpleUSB node", rxchannel="SimpleUSB/4321",
                     simpleusb_settings=SimpleUSBSettings()),
                Node(node_number=4322, name="Radio node", rxchannel="Radio/4322",
                     usbradio_settings=USBRadioSettings()),
            ])
        modules = render_database(database)["modules.conf"].decode()
    finally:
        sessions.kw["bind"].dispose()

    module_lines = {line.strip() for line in modules.splitlines()}
    assert "load => chan_simpleusb.so" in module_lines
    assert "load => chan_usbradio.so" in module_lines
    assert "noload => chan_voter.so" in modules
    assert "require => res_usbradio.so" in modules


def test_structured_baselines_generate_unindented_extensions_and_inferred_modules(database):
    sessions = session_factory(database)
    try:
        with sessions() as session:
            assert session.query(ExtensionRule).filter_by(is_default=True).count() > 10
            assert session.query(ModuleDirective).filter_by(is_default=True).count() > 10
            assert session.query(CustomLine).filter_by(file_name="extensions.conf").filter(
                CustomLine.content.like("%exten =>%") | CustomLine.content.like("%same =>%")
            ).count() == 0
            assert session.query(CustomLine).filter_by(file_name="modules.conf").filter(
                CustomLine.content.like("%load%") | CustomLine.content.like("%noload%") |
                CustomLine.content.like("%require%")
            ).count() == 0
        rendered = render_database(database)
    finally:
        sessions.kw["bind"].dispose()

    extensions = rendered["extensions.conf"].decode().splitlines()
    rules = [line for line in extensions if line.startswith(("exten =>", "same =>"))]
    assert rules
    assert all(line == line.lstrip() for line in rules)
    assert not any("enabled in modules.conf" in line for line in rendered["rpt.conf"].decode().splitlines())
    modules = rendered["modules.conf"].decode()
    assert "noload => chan_simpleusb.so" in modules
    assert "noload => chan_usbradio.so" in modules
    assert "noload => res_usbradio.so" in modules


def test_extension_rules_retain_builtin_values_when_overridden_and_can_revert(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            rule = session.query(ExtensionRule).filter_by(context="default", directive="exten").first()
            assert rule is not None
            original = rule.render()
            rule.updated_directive = rule.directive
            rule.updated_extension = rule.extension
            rule.updated_priority = rule.priority
            rule.updated_application = "Hangup"
            rule.updated_arguments = None
            rule.is_custom = True
            assert rule.render() == "exten => i,1,Hangup"
            rule.revert_to_default()
            assert rule.render() == original
            assert rule.is_custom is False
        with sessions.begin() as session:
            directive = session.query(ModuleDirective).filter_by(module="app_rpt.so").one()
            directive.updated_action = "load"
            directive.is_custom = True
            directive.revert_to_default()
            assert directive.effective_action == directive.action == "require"
    finally:
        sessions.kw["bind"].dispose()


def test_structured_file_edits_save_as_overrides_and_keep_defaults(database):
    sessions = session_factory(database)
    try:
        with sessions.begin() as session:
            default_rule = session.query(ExtensionRule).filter_by(
                context="default", directive="exten").first()
            default_render = default_rule.render()
            edited_rule = default_render.replace(",Hangup", ",Answer")
            save_structured_lines(session, "extensions.conf",
                                  {"default": [edited_rule]}, replace_defaults=False)
            assert default_rule.is_default is True
            assert default_rule.is_custom is True
            assert default_rule.render() == edited_rule
            default_rule.revert_to_default()
            assert default_rule.render() == default_render

            default_module = session.query(ModuleDirective).filter_by(module="app_rpt.so").one()
            save_structured_lines(session, "modules.conf",
                                  {"modules": ["load => app_rpt.so"]}, replace_defaults=False)
            assert default_module.is_default is True
            assert default_module.is_custom is True
            assert default_module.effective_action == "load"
            default_module.revert_to_default()
            assert default_module.effective_action == "require"
    finally:
        sessions.kw["bind"].dispose()


def test_ast_template_sections_are_rendered_as_concrete_sections(database):
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

    assert "[alpha]" in rendered
    assert "[alpha](zbase)" not in rendered
    assert "[zbase](!)" not in rendered
    assert "priorityjumping = no" in rendered
    assert rendered.count("[alpha]") == 1


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

    assert rendered.index('#include "rpt-templates.conf"') < rendered.index("[alpha]")
    assert "duplex = 0" in rendered
    assert "[zbase](!)" not in rendered
    assert "functions = 1" in rendered
    assert "duplex = 0" in rendered
