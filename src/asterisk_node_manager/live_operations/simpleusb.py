"""Fixed SimpleUSB CLI operations."""

from __future__ import annotations

from .base import LiveOperation, OperationContext, OperationError, validate_device


class SimpleUSBOperations(LiveOperation):
    driver = "simpleusb"
    tuning_fields = {"rx": (0, 999), "txa": (0, 999), "txb": (0, 999)}

    def list_devices(self) -> str:
        return self.cli.run("susb active")

    def read_settings(self, context: OperationContext) -> str:
        device = validate_device(context.device)
        self.cli.run(f"susb active {device}")
        return self.cli.run("susb show settings")

    def set_value(self, context: OperationContext, setting: str, value: object) -> str:
        if setting not in self.tuning_fields:
            raise OperationError(f"Unsupported SimpleUSB tuning setting: {setting}.")
        minimum, maximum = self.tuning_fields[setting]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise OperationError(f"{setting} must be an integer from {minimum} to {maximum}.")
        device = validate_device(context.device)
        self.cli.run(f"susb active {device}")
        return self.cli.run(f"susb tune {setting} {value}")
