"""Explicit registry for supported live operations."""

from __future__ import annotations

from pathlib import Path

from .simpleusb import SimpleUSBOperations
from .usbradio import USBRadioOperations
from .base import AsteriskSocket, OperationContext, OperationError, validate_node_number


DRIVERS = {"simpleusb": SimpleUSBOperations, "usbradio": USBRadioOperations}
OPERATIONS = {"list_devices", "read_settings", "set_value", "reload_driver"}


def operation_names() -> dict[str, tuple[str, ...]]:
    return {name: tuple(driver.tuning_fields) for name, driver in DRIVERS.items()}


def execute_operation(asterisk_socket: Path, driver: str, operation: str,
                      node_number: int | None = None, device: str | None = None,
                      setting: str | None = None, value: object = None) -> dict:
    if driver not in DRIVERS:
        raise OperationError("driver must be 'simpleusb' or 'usbradio'.")
    if operation not in OPERATIONS:
        raise OperationError("operation must be list_devices, read_settings, set_value, or reload_driver.")
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
    if not isinstance(setting, str):
        raise OperationError("setting is required for set_value.")
    return {"output": implementation.set_value(context, setting, value)}
