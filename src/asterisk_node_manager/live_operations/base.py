"""Shared execution primitives for live Asterisk operations."""

from __future__ import annotations

import re
import selectors
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


MAX_OUTPUT_BYTES = 64 * 1024
COMMAND_TIMEOUT_SECONDS = 10
DEVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class OperationError(ValueError):
    """A safe, user-facing live operation failure."""


@dataclass(frozen=True)
class OperationContext:
    asterisk_cli: Path
    node_number: int
    device: str


class LiveOperation(ABC):
    """Base contract implemented by each explicitly registered radio driver."""

    driver: str
    tuning_fields: dict[str, tuple[int, int]]

    def __init__(self, cli: AsteriskCLI):
        self.cli = cli

    @abstractmethod
    def list_devices(self) -> str:
        """Return the driver's supported or active device list."""

    @abstractmethod
    def read_settings(self, context: OperationContext) -> str:
        """Read current runtime tuning values for one configured device."""

    @abstractmethod
    def set_value(self, context: OperationContext, setting: str, value: object) -> str:
        """Apply one validated live tuning value."""


class AsteriskCLI:
    """Run a fixed-form Asterisk CLI command through its local control socket."""

    def __init__(self, executable: Path):
        self.executable = executable
        self.deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS

    def run(self, command: str) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise OperationError("Asterisk CLI operation exceeded the 10 second limit.")
        process = None
        try:
            process = subprocess.Popen(
                [str(self.executable), "-rx", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise OperationError(
                f"Asterisk CLI executable was not found at {self.executable}. "
                "Set paths.asterisk_cli to the installed asterisk executable."
            ) from exc
        except PermissionError as exc:
            raise OperationError(
                "The web service cannot access the Asterisk control socket. "
                "Grant its service account access to the configured Asterisk CLI socket, "
                "then restart the web service."
            ) from exc
        except OSError as exc:
            if exc.errno in {13, 1}:
                raise OperationError(
                    "The web service cannot access the Asterisk control socket. "
                    "Grant its service account access to the configured Asterisk CLI socket, "
                    "then restart the web service."
                ) from exc
            raise OperationError(f"Could not connect to the Asterisk control socket: {exc}") from exc

        assert process.stdout is not None
        output = bytearray()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while selector.get_map():
                remaining = self.deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    process.kill()
                    process.wait()
                    raise OperationError("Asterisk CLI operation exceeded the 10 second limit.")
                chunk = process.stdout.read1(4096)
                if not chunk:
                    selector.unregister(process.stdout)
                    break
                output.extend(chunk)
                if len(output) > MAX_OUTPUT_BYTES:
                    process.kill()
                    process.wait()
                    raise OperationError("Asterisk CLI output exceeded the 64 KiB limit.")
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise OperationError("Asterisk CLI operation exceeded the 10 second limit.")
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise OperationError("Asterisk CLI operation exceeded the 10 second limit.") from exc
        finally:
            selector.close()
            process.stdout.close()

        message = output.decode("utf-8", errors="replace").strip()
        if "no such command" in message.lower():
            raise OperationError(message)
        if returncode != 0:
            lowered = message.lower()
            if "permission denied" in lowered or "operation not permitted" in lowered:
                raise OperationError(
                    "The web service cannot access the Asterisk control socket. "
                    "Grant its service account access to the configured Asterisk CLI socket, "
                    "then restart the web service."
                )
            if "unable to connect" in lowered or "no such file" in lowered:
                raise OperationError(
                    "Could not connect to the Asterisk control socket. Confirm Asterisk is running "
                    "and that the configured Asterisk CLI uses its socket path."
                )
            raise OperationError(message or "Asterisk CLI command failed.")
        return message


def validate_node_number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 2**63 - 1:
        raise OperationError("node_number must be an integer from 1000 to 2^63 - 1.")
    return value


def validate_device(value: str) -> str:
    if not DEVICE_NAME.fullmatch(value):
        raise OperationError("The configured USB device name contains unsupported characters.")
    return value
