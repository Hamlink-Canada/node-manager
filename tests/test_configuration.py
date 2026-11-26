Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
from asterisk_node_manager.configuration import (
    apply_node_config_values,
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
    assert "simpleusb" not in {field["key"] for group in groups for field in group["fields"]}


def test_validation_rejects_invalid_numeric_values_and_normalizes_valid_values():
    values, errors = validate_node_settings({"duplex": "9", "hangtime": "-1"}, 1234)
    assert values is None
    assert set(errors) == {"duplex", "hangtime"}

    values, errors = validate_node_settings({"duplex": "0", "hangtime": "2500"}, 1234)
    assert errors == {}
    assert values["duplex"] == "0"
    assert values["hangtime"] == "2500"


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
