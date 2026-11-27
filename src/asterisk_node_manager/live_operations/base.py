"""Shared execution primitives for live Asterisk operations."""

from __future__ import annotations

import errno
import re
import socket
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


MAX_OUTPUT_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 511
COMMAND_TIMEOUT_SECONDS = 10
GREETING_LIMIT_BYTES = 1024
DEVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
COMMAND_PREFIX = b"cli quit after "


class OperationError(ValueError):
    """A safe, user-facing live operation failure."""


@dataclass(frozen=True)
class OperationContext:
    node_number: int
    device: str


class LiveOperation(ABC):
    """Base contract implemented by each explicitly registered radio driver."""

    driver: str
    module_name: str
    tuning_fields: dict[str, tuple[int, int]]

    def __init__(self, cli: AsteriskSocket):
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

    def reload_driver(self) -> str:
        """Reload only the registered channel driver module."""
        result = self.cli.run(f"module reload {self.module_name}")
        if any(marker in result.lower() for marker in ("reload failed", "unable to reload", "no such module")):
            raise OperationError(result)
        return result


class AsteriskSocket:
    """Run a fixed-form Asterisk CLI command over its Unix control socket."""

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self.deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS

    def run(self, command: str) -> str:
        if not command or any(character in command for character in "\0\r\n"):
            raise OperationError("Provide one non-empty Asterisk CLI command on a single line.")
        request = COMMAND_PREFIX + command.encode("utf-8") + b"\0"
        if len(request) > MAX_REQUEST_BYTES:
            raise OperationError("Asterisk CLI command is too long for the control socket.")

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._set_timeout(client)
            client.connect(str(self.socket_path))
            self._read_greeting(client)
            self._set_timeout(client)
            client.sendall(request)
            output = self._read_response(client)
        except OperationError:
            raise
        except socket.timeout as exc:
            raise OperationError("Asterisk CLI operation exceeded the 10 second limit.") from exc
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                raise OperationError(
                    "The web service cannot access the Asterisk control socket. "
                    "Grant its service account access to the configured socket, then restart the web service."
                ) from exc
            if exc.errno == errno.ENOENT:
                raise OperationError(
                    f"Asterisk control socket was not found at {self.socket_path}. "
                    "Set paths.asterisk_socket to the active Asterisk socket and restart the web service."
                ) from exc
            raise OperationError(f"Could not connect to the Asterisk control socket: {exc}") from exc
        finally:
            client.close()

        message = output.decode("utf-8", errors="replace").strip()
        if "no such command" in message.lower():
            raise OperationError(message)
        return message

    def _set_timeout(self, client: socket.socket) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise OperationError("Asterisk CLI operation exceeded the 10 second limit.")
        client.settimeout(remaining)

    def _read_greeting(self, client: socket.socket) -> None:
        greeting = bytearray()
        while b"\n" not in greeting:
            self._set_timeout(client)
            chunk = client.recv(256)
            if not chunk:
                raise OperationError(
                    "The Asterisk control socket closed before sending its greeting. "
                    "Check that the service and socket forwarding are available."
                )
            greeting.extend(chunk)
            if len(greeting) > GREETING_LIMIT_BYTES:
                raise OperationError("Asterisk control socket greeting exceeded 1 KiB.")

    def _read_response(self, client: socket.socket) -> bytes:
        output = bytearray()
        while True:
            self._set_timeout(client)
            chunk = client.recv(4096)
            if not chunk:
                return bytes(output)
            output.extend(chunk)
            if len(output) > MAX_OUTPUT_BYTES:
                raise OperationError("Asterisk CLI output exceeded the 64 KiB limit.")


def validate_node_number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 2**63 - 1:
        raise OperationError("node_number must be an integer from 1000 to 2^63 - 1.")
    return value


def validate_device(value: str) -> str:
    if not DEVICE_NAME.fullmatch(value):
        raise OperationError("The configured USB device name contains unsupported characters.")
    return value
