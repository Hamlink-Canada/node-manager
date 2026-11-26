import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from asterisk_node_manager import writer


def _request(payload):
    return json.dumps(payload).encode()


def test_writer_rejects_invalid_json_and_unsupported_operations(tmp_path):
    settings = SimpleNamespace(pam_service="manager", database=tmp_path / "db.sqlite",
                               asterisk_directory=tmp_path / "asterisk")
    assert writer.handle_request(b"not json", settings) == {"ok": False, "error": "invalid JSON request"}
    assert writer.handle_request(_request({"operation": "shell"}), settings) == {
        "ok": False, "error": "unsupported operation"
    }
    assert writer.handle_request(_request({"operation": []}), settings) == {
        "ok": False, "error": "unsupported operation"
    }


def test_writer_response_reader_handles_large_replies_and_rejects_empty_reply():
    class FakeSocket:
        def __init__(self, chunks):
            self.chunks = iter(chunks)

        def recv(self, _size):
            return next(self.chunks, b"")

    payload = json.dumps({"ok": True, "output": "x" * 70000}).encode()
    from asterisk_node_manager.web import _read_writer_response
    result = _read_writer_response(FakeSocket([payload[:20000], payload[20000:]]))
    assert len(result["output"]) == 70000
    with pytest.raises(OSError, match="without a response"):
        _read_writer_response(FakeSocket([]))


def test_demo_file_publication_rolls_back_when_a_later_replace_fails(monkeypatch, tmp_path):
    directory = tmp_path / "demo-output"
    directory.mkdir()
    (directory / "one.conf").write_bytes(b"old-one")
    (directory / "two.conf").write_bytes(b"old-two")
    original_replace = os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        return original_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second)
    from asterisk_node_manager.web import _write_demo_files
    with pytest.raises(OSError, match="simulated replace failure"):
        _write_demo_files(directory, {"one.conf": b"new-one", "two.conf": b"new-two"})
    assert (directory / "one.conf").read_bytes() == b"old-one"
    assert (directory / "two.conf").read_bytes() == b"old-two"


def test_writer_limits_diagnostic_commands(monkeypatch, tmp_path):
    settings = SimpleNamespace(pam_service="manager", database=tmp_path / "db.sqlite",
                               asterisk_directory=tmp_path / "asterisk", asterisk_cli=Path("/usr/sbin/asterisk"))
    response = writer.handle_request(_request({"operation": "diagnostic", "command": "rm -rf /"}), settings)
    assert response == {"ok": False, "error": "diagnostic command is not allowed"}

    monkeypatch.setattr(writer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="version output", stderr=""))
    response = writer.handle_request(_request({"operation": "diagnostic", "command": "core show version"}), settings)
    assert response == {"ok": True, "output": "version output"}


def test_writer_rejects_invalid_authentication_payload_without_pam_call(monkeypatch, tmp_path):
    settings = SimpleNamespace(pam_service="manager", database=tmp_path / "db.sqlite",
                               asterisk_directory=tmp_path / "asterisk")
    monkeypatch.setattr(writer.pam, "authenticate", lambda *args, **kwargs: pytest.fail("PAM must not be called"))
    response = writer.handle_request(_request({"operation": "authenticate", "username": "user",
                                               "password": "pass", "service": "other"}), settings)
    assert response == {"ok": True, "authenticated": False}


def test_file_replacement_restores_all_original_files_on_failure(monkeypatch, tmp_path):
    directory = tmp_path / "asterisk"
    directory.mkdir()
    (directory / "one.conf").write_bytes(b"old-one")
    (directory / "two.conf").write_bytes(b"old-two")
    original_replace = os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        return original_replace(source, target)

    monkeypatch.setattr(writer.os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        writer._replace_files(directory, {"one.conf": b"new-one", "two.conf": b"new-two"})
    assert (directory / "one.conf").read_bytes() == b"old-one"
    assert (directory / "two.conf").read_bytes() == b"old-two"
