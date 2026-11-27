"""Explicit registry for supported live operations."""

from __future__ import annotations

from pathlib import Path

from .simpleusb import SimpleUSBOperations
from .usbradio import USBRadioOperations
from .base import AsteriskSocket, OperationContext, OperationError, validate_node_number
from .queries import execute_query


DRIVERS = {"simpleusb": SimpleUSBOperations, "usbradio": USBRadioOperations}
OPERATIONS = {"list_devices", "read_settings", "read_signal", "set_value", "reload_driver"}


def operation_names() -> dict[str, tuple[str, ...]]:
    return {name: tuple(driver.tuning_fields) for name, driver in DRIVERS.items()}


def execute_operation(asterisk_socket: Path, driver: str, operation: str,
                      node_number: int | None = None, device: str | None = None,
                      setting: str | None = None, value: object = None) -> dict:
    if driver not in DRIVERS:
        raise OperationError("driver must be 'simpleusb' or 'usbradio'.")
    if operation not in OPERATIONS:
        raise OperationError(
            "operation must be list_devices, read_settings, read_signal, set_value, or reload_driver."
        )
    cli = AsteriskSocket(asterisk_socket)
    implementation = DRIVERS[driver](cli)
    if operation == "list_devices":
        return {"output": implementation.list_devices()}
    if operation == "reload_driver":
        return {"output": implementation.reload_driver()}
    validated_node = validate_node_number(node_number)
    if not isinstance(device, str) or not device:
        raise OperationError("The configured interface device could not be resolved for this Node Number.")
    context = OperationContext(validated_node, device)
    if operation == "read_settings":
        return {"output": implementation.read_settings(context)}
    if operation == "read_signal":
        if driver != "usbradio":
            raise OperationError("read_signal is only supported by the USBRadio driver.")
        return {"output": implementation.read_signal(context)}
    if not isinstance(setting, str):
        raise OperationError("setting is required for set_value.")
    return {"output": implementation.set_value(context, setting, value)}


def execute_asterisk_query(asterisk_socket: Path, query: str) -> dict[str, str]:
    """Run a named read-only Asterisk query through the shared socket transport."""
    return execute_query(asterisk_socket, query)
