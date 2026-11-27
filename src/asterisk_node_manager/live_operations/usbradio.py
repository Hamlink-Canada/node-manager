"""Fixed USBRadio CLI operations."""

from __future__ import annotations

from .base import LiveOperation, OperationContext, OperationError, validate_device


class USBRadioOperations(LiveOperation):
    driver = "usbradio"
    module_name = "chan_usbradio.so"
    tuning_fields = {
        "rxsquelch": (0, 999),
        "txvoice": (0, 999),
        "txtone": (0, 999),
        "auxvoice": (0, 999),
        "txslimsp": (5000, 13000),
    }

    def _select_device(self, device: str) -> None:
        result = self.cli.run(f"radio active {device}")
        if any(marker in result.lower() for marker in (
            "no device [", "device not found", "does not exist", "no such device",
        )):
            raise OperationError(result or "Asterisk rejected the configured device selection.")

    def list_devices(self) -> str:
        return self.cli.run("radio active show")

    def read_settings(self, context: OperationContext) -> str:
        device = validate_device(context.device)
        self._select_device(device)
        settings = self.cli.run("radio show settings")
        # `radio show settings` omits the configurable soft-limiter setpoint;
        # the no-argument query is read-only and reports its current value.
        limiter = self.cli.run("radio tune txslimsp")
        return "\n".join(part for part in (settings, limiter) if part)

    def read_signal(self, context: OperationContext) -> str:
        """Read current RSSI and squelch threshold without changing either value."""
        device = validate_device(context.device)
        self._select_device(device)
        return self.cli.run("radio tune rxsquelch")

    def set_value(self, context: OperationContext, setting: str, value: object) -> str:
        if setting not in self.tuning_fields:
            raise OperationError(f"Unsupported USBRadio tuning setting: {setting}.")
        minimum, maximum = self.tuning_fields[setting]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise OperationError(f"{setting} must be an integer from {minimum} to {maximum}.")
        device = validate_device(context.device)
        self._select_device(device)
        result = self.cli.run(f"radio tune {setting} {value}")
        if setting == "txslimsp":
            # This command changes the limiter without printing a success
            # message, so read its value back for a useful task result.
            result = self.cli.run("radio tune txslimsp")
        return result
