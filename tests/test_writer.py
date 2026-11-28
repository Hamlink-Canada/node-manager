import json
import os
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
    deeply_nested_json = b"[" * 10_000 + b"0" + b"]" * 10_000
    deeply_nested_response = writer.handle_request(deeply_nested_json, settings)
    # Python releases differ in whether json.loads rejects this nesting as a
    # recursion error or parses it and lets the protocol reject the list root.
    assert deeply_nested_response["ok"] is False
    assert deeply_nested_response["error"] in {"invalid JSON request", "unsupported operation"}


def test_writer_shutdown_handler_exits_through_cleanup_path():
    with pytest.raises(SystemExit) as exc_info:
        writer._handle_shutdown(15, None)
    assert exc_info.value.code == 0


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


def test_writer_rejects_removed_diagnostic_operation():
    response = writer.handle_request(_request({"operation": "diagnostic", "command": "core show version"}),
                                     SimpleNamespace())
    assert response == {"ok": False, "error": "unsupported operation"}


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


def test_file_replacement_rolls_back_before_propagating_shutdown(monkeypatch, tmp_path):
    directory = tmp_path / "asterisk"
    directory.mkdir()
    (directory / "one.conf").write_bytes(b"old-one")
    (directory / "two.conf").write_bytes(b"old-two")
    original_replace = os.replace
    calls = 0

    def stop_during_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SystemExit(0)
        return original_replace(source, target)

    monkeypatch.setattr(writer.os, "replace", stop_during_second_replace)
    with pytest.raises(SystemExit):
        writer._replace_files(directory, {"one.conf": b"new-one", "two.conf": b"new-two"})
    assert (directory / "one.conf").read_bytes() == b"old-one"
    assert (directory / "two.conf").read_bytes() == b"old-two"
