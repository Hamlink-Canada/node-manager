"""Fixed SimpleUSB CLI operations."""

from __future__ import annotations

from .base import (
    LiveOperation,
    OperationContext,
    OperationError,
    confirm_active_device,
    confirm_settings_device,
    validate_device,
)


class SimpleUSBOperations(LiveOperation):
    driver = "simpleusb"
    module_name = "chan_simpleusb.so"
    tuning_fields = {"rx": (0, 999), "txa": (0, 999), "txb": (0, 999)}

    def _select_device(self, device: str) -> None:
        result = self.cli.run(f"susb active {device}")
        confirm_active_device(result, device, "SimpleUSB")

    def list_devices(self) -> str:
        # `show` lists every device known to the channel driver, including
        # the device string and ALSA card assigned to each configured node.
        return self.cli.run("susb active show")

    def read_settings(self, context: OperationContext) -> str:
        device = validate_device(context.device)
        self._select_device(device)
        result = self.cli.run("susb show settings")
        confirm_settings_device(result, device, "SimpleUSB")
        return result

    def set_value(self, context: OperationContext, setting: str, value: object) -> str:
        if setting not in self.tuning_fields:
            raise OperationError(f"Unsupported SimpleUSB tuning setting: {setting}.")
        minimum, maximum = self.tuning_fields[setting]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise OperationError(f"{setting} must be an integer from {minimum} to {maximum}.")
        device = validate_device(context.device)
        self._select_device(device)
        return self.cli.run(f"susb tune {setting} {value}")
