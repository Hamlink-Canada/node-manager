"""Narrow privileged Unix socket endpoint for generated configuration writes."""

from __future__ import annotations

import grp
import json
import logging
import os
import signal
import socket
import stat
import tempfile
from pathlib import Path

import pam

from .config import load_settings
from .database import database_exists, database_write_lock
from .networks import load_network_profiles
from .generate import render_database

ALLOWED_OPERATIONS = {"generate", "authenticate"}


def _handle_shutdown(signum, _frame):
    logging.getLogger(__name__).info("Received signal %s; stopping writer", signum)
    # SystemExit unwinds main()'s finally block, which closes and removes the
    # Unix socket. The handler is required because this process may run as PID 1.
    raise SystemExit(0)


def handle_request(request: bytes, settings) -> dict:
    try:
        payload = json.loads(request.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return {"ok": False, "error": "invalid JSON request"}
    if (not isinstance(payload, dict) or not isinstance(payload.get("operation"), str)
            or payload.get("operation") not in ALLOWED_OPERATIONS):
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
    try:
        generated = render_database(
            settings.database, network_profiles_enabled=settings.network_profiles_enabled,
            default_network=settings.default_network)
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
    except BaseException:
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    if not settings.demo_mode and database_exists(settings.database):
        with database_write_lock(settings.database):
            loaded_profiles = load_network_profiles(
                settings.network_profiles_directory, settings.database)
        if loaded_profiles:
            logging.getLogger(__name__).info("Loaded %d network profile files from %s",
                                             loaded_profiles, settings.network_profiles_directory)
    server, owns_socket_path = _open_server_socket(settings)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    try:
        # Reconcile interrupted publication before serving clients when a database exists.
        if not settings.demo_mode and database_exists(settings.database):
            _replace_files(settings.asterisk_directory, render_database(
                settings.database, network_profiles_enabled=settings.network_profiles_enabled,
                default_network=settings.default_network))
        while True:
            connection, _ = server.accept()
            with connection:
                try:
                    connection.settimeout(10)
                    request = _read_request(connection)
                    response = handle_request(request, settings)
                    connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
                except (OSError, ValueError, TypeError, RecursionError):
                    # One malformed or abandoned client must not stop the listener.
                    continue
    finally:
        server.close()
        if owns_socket_path:
            settings.writer_socket.unlink(missing_ok=True)


def _open_server_socket(settings):
    activated = (os.environ.get("LISTEN_PID") == str(os.getpid())
                 and int(os.environ.get("LISTEN_FDS", "0")) >= 1)
    if activated:
        return socket.socket(fileno=3), False
    if os.geteuid() != 0:
        raise PermissionError("standalone writer helper must run as root")

    socket_path = settings.writer_socket
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        if not socket_path.is_socket():
            raise RuntimeError(f"Writer socket path exists and is not a socket: {socket_path}")
        socket_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        server.listen(32)
        os.chmod(socket_path, 0o660)
        try:
            group_id = grp.getgrnam("asterisk-node-manager").gr_gid
            os.chown(socket_path, 0, group_id)
        except KeyError:
            pass
    except Exception:
        server.close()
        socket_path.unlink(missing_ok=True)
        raise
    return server, True


def _read_request(connection: socket.socket) -> bytes:
    chunks = bytearray()
    while True:
        chunk = connection.recv(16384)
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > 1_048_576:
            raise ValueError("request exceeds the 1 MiB limit")
        if b"\n" in chunk:
            break
    if not chunks:
        raise ValueError("empty request")
    return bytes(chunks).split(b"\n", 1)[0]


if __name__ == "__main__":
    raise SystemExit(main())
