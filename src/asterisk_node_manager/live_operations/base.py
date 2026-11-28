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
CLI_ERROR_PREFIX = re.compile(
    r"^(?:error\b|failed\b|unable\b|invalid\b|unknown\b|usage:|no such command\b|no device\s*\[)",
    re.IGNORECASE,
)


class OperationError(ValueError):
    """A safe, user-facing live operation failure."""

    def __init__(self, message: str, *, outcome_unknown: bool = False):
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


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
        if CLI_ERROR_PREFIX.match(result) or any(marker in result.lower() for marker in (
            "reload failed", "unable to reload", "no such module",
        )):
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
        command_sent = False
        try:
            self._set_timeout(client)
            client.connect(str(self.socket_path))
            self._read_greeting(client)
            self._set_timeout(client)
            # Treat send errors as uncertain too: sendall may have written a
            # prefix (or the complete command) before the socket failed.
            command_sent = True
            client.sendall(request)
            output = self._read_response(client)
        except OperationError as exc:
            if command_sent:
                raise OperationError(
                    f"{exc} Asterisk received the command, but its outcome could not be confirmed; "
                    "read the current settings before retrying.",
                    outcome_unknown=True,
                ) from exc
            raise
        except socket.timeout as exc:
            raise self._socket_failure(
                "Asterisk CLI operation exceeded the 10 second limit.", command_sent
            ) from exc
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                message = (
                    "The web service cannot access the Asterisk control socket. "
                    "Grant its service account access to the configured socket, then restart the web service."
                )
            elif exc.errno == errno.ENOENT:
                message = (
                    "Asterisk control socket was not found. Set paths.asterisk_socket to the active "
                    "socket and restart the web service."
                )
            elif exc.errno == errno.ECONNREFUSED:
                message = (
                    "Asterisk control socket refused the connection. Check that Asterisk and its "
                    "socket listener are running, then retry."
                )
            else:
                message = f"Could not communicate with the Asterisk control socket (OS error {exc.errno})."
            raise self._socket_failure(message, command_sent) from exc
        finally:
            client.close()

        message = output.decode("utf-8", errors="replace").strip()
        if not message:
            raise OperationError(
                "Asterisk returned an empty response. The command may have taken effect; "
                "read the current settings before retrying.",
                outcome_unknown=True,
            )
        if CLI_ERROR_PREFIX.match(message):
            raise OperationError(message)
        return message

    @staticmethod
    def _socket_failure(message: str, command_sent: bool) -> OperationError:
        if command_sent:
            message += (
                " Asterisk received the command, but its outcome could not be confirmed; "
                "read the current settings before retrying."
            )
        return OperationError(message, outcome_unknown=command_sent)

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


def validate_device(value: object) -> str:
    if not isinstance(value, str) or not DEVICE_NAME.fullmatch(value):
        raise OperationError("The configured USB device name contains unsupported characters.")
    if value.lower() == "show":
        raise OperationError(
            "The device name 'show' is reserved by the Asterisk CLI. Rename the configured device."
        )
    return value


def confirm_active_device(response: str, device: str, driver: str) -> None:
    """Stop if Asterisk did not confirm the requested interface is active."""
    message = response.strip()
    if CLI_ERROR_PREFIX.match(message):
        raise OperationError(message)
    match = re.search(r"\bactive\b[^\r\n]*\[([^\]]+)\]", message, re.IGNORECASE)
    if match is None:
        raise OperationError(
            f"Asterisk did not confirm that the {driver} interface [{device}] became active; "
            "no follow-up command was sent."
        )
    active_device = match.group(1).strip()
    if active_device != device:
        raise OperationError(
            f"Asterisk activated {driver} interface [{active_device}] instead of [{device}]; "
            "no follow-up command was sent."
        )


def confirm_settings_device(response: str, device: str, driver: str) -> None:
    """Ensure a settings read belongs to the interface selected for this task."""
    match = re.search(
        r"^\s*Active radio interface is \[([^\]]+)\]\s*$",
        response,
        re.IGNORECASE | re.MULTILINE,
    )
    if match is None:
        raise OperationError(
            f"Asterisk did not identify the active {driver} interface in its settings response. "
            "Check that the driver is loaded and the device is assigned to this Node Number."
        )
    active_device = match.group(1).strip()
    if active_device != device:
        raise OperationError(
            f"Asterisk returned {driver} settings for interface [{active_device}] while "
            f"[{device}] was requested. No settings were accepted."
        )
