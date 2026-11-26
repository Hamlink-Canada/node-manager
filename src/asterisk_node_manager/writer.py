"""Narrow privileged Unix socket endpoint for generated configuration writes."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import stat
import sys
import tempfile
import grp

import pam
from pathlib import Path

from .config import load_settings
from .generate import render_database

ALLOWED_OPERATIONS = {"generate", "diagnostic", "authenticate"}
DIAGNOSTIC_COMMANDS = {
    "core show version", "core show uptime", "core show channels",
    "iax2 show peers", "rpt show nodes", "module show",
}


def handle_request(request: bytes, settings) -> dict:
    try:
        payload = json.loads(request.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "error": "invalid JSON request"}
    if not isinstance(payload, dict) or payload.get("operation") not in ALLOWED_OPERATIONS:
        return {"ok": False, "error": "unsupported operation"}
    if payload["operation"] == "authenticate":
        username, password = payload.get("username"), payload.get("password")
        service = payload.get("service")
        if (not isinstance(username, str) or not username or len(username) > 256
                or any(char in username for char in "\r\n\x00")
                or not isinstance(password, str) or not password or len(password) > 4096
                or service != settings.pam_service):
            return {"ok": True, "authenticated": False}
        try:
            authenticated = pam.authenticate(username, password, service=service, resetcreds=False)
        except Exception:
            authenticated = False
        return {"ok": True, "authenticated": bool(authenticated)}
    revision = payload.get("revision")
    if revision is not None and (not isinstance(revision, int) or revision < 0):
        return {"ok": False, "error": "invalid revision"}
    if payload["operation"] == "diagnostic":
        command = payload.get("command")
        if command not in DIAGNOSTIC_COMMANDS:
            return {"ok": False, "error": "diagnostic command is not allowed"}
        try:
            result = subprocess.run([str(settings.asterisk_cli), "-rx", command],
                                    check=False, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": f"Asterisk command failed: {exc}"}
        return {"ok": result.returncode == 0, "output": result.stdout or result.stderr}
    try:
        generated = render_database(settings.database)
        _replace_files(settings.asterisk_directory, generated)
    except Exception as exc:
        return {"ok": False, "error": f"generation failed: {exc}"}
    return {"ok": True, "files": sorted(generated)}


def _replace_files(directory: Path, files: dict[str, bytes]) -> None:
    """Stage generated files and restore prior contents if replacement fails."""
    directory.mkdir(parents=True, exist_ok=True)
    snapshots: dict[str, tuple[bytes, int, int, int] | None] = {}
    staged: dict[str, Path] = {}
    try:
        for name, content in files.items():
            target = directory / name
            if target.parent != directory or target.name != name:
                raise ValueError("unsafe generated filename")
            if target.exists():
                target_stat = target.stat()
                snapshots[name] = (target.read_bytes(), stat.S_IMODE(target_stat.st_mode),
                                   target_stat.st_uid, target_stat.st_gid)
            else:
                snapshots[name] = None
            with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.", delete=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                if snapshots[name] is None:
                    try:
                        target_gid = grp.getgrnam("asterisk").gr_gid
                    except KeyError:
                        target_gid = 0
                    os.fchown(stream.fileno(), 0, target_gid)
                    os.fchmod(stream.fileno(), 0o640)
                else:
                    _, mode, uid, gid = snapshots[name]
                    os.fchown(stream.fileno(), uid, gid)
                    os.fchmod(stream.fileno(), mode)
                staged[name] = Path(stream.name)
        for name, temporary in staged.items():
            os.replace(temporary, directory / name)
    except Exception:
        for name, previous in snapshots.items():
            target = directory / name
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                content, mode, uid, gid = previous
                with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.restore.", delete=False) as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchown(stream.fileno(), uid, gid)
                    os.fchmod(stream.fileno(), mode)
                    restore_path = Path(stream.name)
                os.replace(restore_path, target)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def main() -> int:
    settings = load_settings()
    if not os.path.exists(settings.writer_socket):
        print("Writer socket must be provided by systemd socket activation", file=sys.stderr)
        return 2
    # systemd passes the listening socket as descriptor 3.
    server = socket.socket(fileno=3)
    while True:
        connection, _ = server.accept()
        with connection:
            request = connection.recv(65536)
            response = handle_request(request, settings)
            connection.sendall(json.dumps(response).encode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
