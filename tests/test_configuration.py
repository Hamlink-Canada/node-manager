from asterisk_node_manager.configuration import (
    apply_interface_config_values,
    apply_node_config_values,
    interface_config_values,
    node_config_values,
    node_field_groups,
    validate_node_settings,
)
from asterisk_node_manager.models import Node


def test_configuration_groups_put_basic_radio_and_tuning_in_default_view():
    groups = node_field_groups(1234, {"rxchannel": "SimpleUSB/1234", "duplex": "0"})
    basic = [group for group in groups if not group["advanced"]]
    advanced = [group for group in groups if group["advanced"]]

    assert {group["title"] for group in basic} == {"Radio and channel", "SimpleUSB radio interface"}
    assert all("linktolink" not in {field["key"] for field in group["fields"]} for group in basic)
    assert "linktolink" in {field["key"] for group in advanced for field in group["fields"]}


def test_configuration_hides_simpleusb_fields_when_another_channel_is_selected():
    groups = node_field_groups(1234, {"rxchannel": "Local/pseudo"})
    assert not any(field.get("file") == "simpleusb.conf"
                   for group in groups for field in group["fields"])


def test_defaults_are_displayed_and_saved_as_sparse_overrides(monkeypatch):
    import asterisk_node_manager.configuration as configuration

    required_field = {"key": "required_fixture", "group": "required_fixture",
                      "kind": "text", "required": True, "max": 40}
    monkeypatch.setattr(configuration, "_FIELD_DEFINITIONS",
                        (*configuration._FIELD_DEFINITIONS, required_field))
    fields = {field["key"]: field for group in node_field_groups(1234, {})
              for field in group["fields"]}
    assert fields["hangtime"]["value"] == "5000"
    assert fields["hangtime"]["default_value"] == "5000"
    assert fields["hangtime"]["has_default"] is True
    assert fields["required_fixture"]["value"] == ""
    assert fields["required_fixture"]["has_default"] is False
    assert fields["required_fixture"]["required"] is True
    values, errors = validate_node_settings({}, 1234)
    assert values is None
    assert errors["required_fixture"] == "This field is required."
    _, errors = validate_node_settings({"required_fixture": ""}, 1234)
    assert errors["required_fixture"] == "This field is required."

    node = Node(node_number=1234, name="Node 1234")
    apply_node_config_values(node, {"hangtime": "5000", "linktolink": "no"})
    assert node.hangtime is None
    assert node.linktolink is None
    assert node_config_values(node)["hangtime"] == "5000"
    assert node_config_values(node)["linktolink"] == "no"


def test_radio_interface_defaults_are_sparse_and_restored_for_display():
    from asterisk_node_manager.models import USBRadioSettings

    radio = USBRadioSettings()
    apply_interface_config_values(radio, "usbradio.conf", {
        "rxboost": "yes", "rxvoiceadj": "0.5", "txctcssdefault": "100.0",
    })
    assert radio.rxboost is None
    assert radio.rxvoiceadj is None
    values = interface_config_values(radio, "usbradio.conf")
    assert values["rxboost"] == "yes"
    assert values["rxvoiceadj"] == "0.5"


def test_configuration_exposes_radio_fields_and_can_build_both_switchable_panels():
    radio_groups = node_field_groups(1234, {"rxchannel": "Radio/1234"})
    radio_fields = {field["form_key"] for group in radio_groups for field in group["fields"]}
    assert "usbradio_rxdemod" in radio_fields
    assert "usbradio_rxvoiceadj" in radio_fields
    assert not any(field["form_key"].startswith("simpleusb_")
                   for group in radio_groups for field in group["fields"])

    all_groups = node_field_groups(1234, {"rxchannel": "SimpleUSB/1234"}, include_other_interfaces=True)
    panels = {group["interface"]: group["active"] for group in all_groups if group["interface"]}
    assert panels == {"SimpleUSB": True, "Radio": False}
    fields = {field["form_key"] for group in all_groups for field in group["fields"]}
    assert {"simpleusb_rxmixerset", "usbradio_rxmixerset"} <= fields


def test_usb_device_identity_fields_are_available_in_default_view_for_both_drivers():
    groups = node_field_groups(1234, {"rxchannel": "SimpleUSB/1234"}, include_other_interfaces=True)
    fields = {field["form_key"]: (group, field)
              for group in groups for field in group["fields"]}
    for key in ("simpleusb_devstr", "simpleusb_serial", "usbradio_devstr", "usbradio_serial"):
        group, field = fields[key]
        assert group["advanced"] is False
        assert field["value"] == ""
        assert field["has_default"] is True
        assert field["help"]


def test_validation_rejects_invalid_numeric_values_and_normalizes_valid_values():
    values, errors = validate_node_settings({"duplex": "9", "hangtime": "-1"}, 1234)
    assert values is None
    assert set(errors) == {"duplex", "hangtime"}

    values, errors = validate_node_settings({"duplex": "0", "hangtime": "2500"}, 1234)
    assert errors == {}
    assert values["duplex"] == "0"
    assert values["hangtime"] == "2500"

    values, errors = validate_node_settings({"usbradio_rxvoiceadj": "0.625"}, 1234)
    assert errors == {}
    assert values["usbradio_rxvoiceadj"] == "0.625"


def test_typed_node_mapping_round_trips_booleans_and_numbers():
    node = Node(node_number=1234, name="Node 1234")
    apply_node_config_values(node, {"rxchannel": "Local/pseudo", "duplex": "3",
                                    "linktolink": "yes", "hangtime": "3000"})

    values = node_config_values(node)
    assert node.duplex == 3
    assert node.linktolink is True
    assert node.hangtime == 3000
    assert values["linktolink"] == "yes"
    assert values["duplex"] == "3"


def test_unchanged_legacy_numbers_remain_valid_for_unrelated_edits():
    existing = {"rxchannel": "Local/pseudo", "duplex": "2", "hangtime": "10000000"}
    values, errors = validate_node_settings({"hangtime": "10000000", "duplex": "0"}, 1234, existing)
    assert errors == {}
    assert values["hangtime"] == "10000000"
