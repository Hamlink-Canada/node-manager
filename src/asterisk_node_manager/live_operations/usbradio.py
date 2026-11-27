"""Fixed USBRadio CLI operations."""

from __future__ import annotations

from .base import LiveOperation, OperationContext, OperationError, validate_device


class USBRadioOperations(LiveOperation):
    driver = "usbradio"
    tuning_fields = {
        "rxsquelch": (0, 999),
        "txvoice": (0, 999),
        "txtone": (0, 999),
        "auxvoice": (0, 999),
        "txslimsp": (5000, 13000),
    }

    def list_devices(self) -> str:
        return self.cli.run("radio active")

    def read_settings(self, context: OperationContext) -> str:
        device = validate_device(context.device)
        self.cli.run(f"radio active {device}")
        return self.cli.run("radio show settings")

    def set_value(self, context: OperationContext, setting: str, value: object) -> str:
        if setting not in self.tuning_fields:
            raise OperationError(f"Unsupported USBRadio tuning setting: {setting}.")
        minimum, maximum = self.tuning_fields[setting]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise OperationError(f"{setting} must be an integer from {minimum} to {maximum}.")
        device = validate_device(context.device)
        self.cli.run(f"radio active {device}")
        return self.cli.run(f"radio tune {setting} {value}")
