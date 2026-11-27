"""Bounded single-worker task queue and TTL/LRU polling state."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .base import OperationError
from .registry import DRIVERS, execute_operation


logger = logging.getLogger(__name__)
TASK_TTL_SECONDS = 60 * 60
TASK_CAPACITY = 500
QUEUE_CAPACITY = 100


@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    actor: str
    driver: str
    operation: str
    node_number: int | None
    device: str | None
    setting: str | None
    value: object
    confirm_transmit: bool = False


class LiveTaskQueue:
    def __init__(self, asterisk_socket: Path, demo_mode: bool = False,
                 clock: Callable[[], float] = time.monotonic):
        self.asterisk_socket = asterisk_socket
        self.demo_mode = demo_mode
        self.clock = clock
        self._queue: queue.Queue[TaskRequest] = queue.Queue(maxsize=QUEUE_CAPACITY)
        self._tasks: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()
        self._demo_defaults = {
            ("simpleusb", "1000"): {"rx": 500, "txa": 500, "txb": 500},
            ("simpleusb", "1001"): {"rx": 500, "txa": 500, "txb": 500},
            ("usbradio", "1002"): {
                "rxlevel": 500, "rxsquelch": 500, "txvoice": 500, "txtone": 200,
                "auxvoice": 500, "txslimsp": 9000,
            },
        }
        self._demo_values = {key: value.copy() for key, value in self._demo_defaults.items()}
        self._thread = threading.Thread(target=self._work, name="asterisk-live-operations", daemon=True)
        self._thread.start()

    def submit(self, actor: str, driver: str, operation: str, node_number: int | None,
               device: str | None, setting: str | None, value: object,
               confirm_transmit: bool = False) -> dict:
        if driver not in DRIVERS:
            raise OperationError("driver must be 'simpleusb' or 'usbradio'.")
        if operation == "set_value":
            fields = DRIVERS[driver].tuning_fields
            if not isinstance(setting, str) or setting not in fields:
                raise OperationError(f"Unsupported {driver} tuning setting: {setting}.")
            minimum, maximum = fields[setting]
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise OperationError(f"{setting} must be an integer from {minimum} to {maximum}.")
        if driver == "usbradio" and operation == "set_value" \
                and setting in {"txvoice", "txtone"} and not confirm_transmit:
            raise OperationError("confirm_transmit is required because this setting keys the transmitter.")
        self._expire()
        task_id = uuid.uuid4().hex
        now = self.clock()
        record = {
            "task_id": task_id,
            "actor": actor,
            "driver": driver,
            "operation": operation,
            "node_number": node_number,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "_updated_monotonic": now,
        }
        task = TaskRequest(task_id, actor, driver, operation, node_number, device, setting, value,
                           confirm_transmit)
        with self._lock:
            try:
                self._queue.put_nowait(task)
            except queue.Full as exc:
                raise queue.Full("Live operation queue is full; retry shortly.") from exc
            self._tasks[task_id] = record
            self._trim()
            public_record = self._public(record)
        self._audit("queued", record)
        return public_record

    def get(self, task_id: str, actor: str) -> dict | None:
        self._expire()
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None or record["actor"] != actor:
                return None
            self._tasks.move_to_end(task_id)
            return self._public(record)

    def _work(self) -> None:
        while True:
            task = self._queue.get()
            with self._lock:
                record = self._tasks.get(task.task_id)
                if record is None:
                    self._queue.task_done()
                    continue
                record["status"] = "running"
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                record["_updated_monotonic"] = self.clock()
            self._audit("started", record)
            try:
                if self.demo_mode:
                    result = self._mock(task)
                    result["simulated"] = True
                else:
                    result = execute_operation(self.asterisk_socket, task.driver, task.operation,
                                               task.node_number, task.device, task.setting, task.value)
                with self._lock:
                    record.update(status="succeeded", result=result,
                                  updated_at=datetime.now(timezone.utc).isoformat(),
                                  _updated_monotonic=self.clock())
                    self._tasks.move_to_end(task.task_id)
                    if task.operation == "set_value":
                        record.update(persisted=False,
                                      warning=self._temporary_warning(task.driver, task.setting))
                        if task.driver == "usbradio" and task.setting in {"txvoice", "txtone"}:
                            record["transmission_warning"] = (
                                "This operation keys the transmitter and sends a 1 kHz test tone "
                                "for about five seconds."
                            )
                    elif task.operation == "reload_driver":
                        record["warning"] = (
                            "Reloading the driver reapplies saved configuration (or the demo "
                            "baseline) and can discard unsaved live tuning changes."
                        )
                    self._trim()
                self._audit("succeeded", record)
            except Exception as exc:
                with self._lock:
                    record.update(status="failed", error=str(exc),
                                  updated_at=datetime.now(timezone.utc).isoformat(),
                                  _updated_monotonic=self.clock())
                    self._tasks.move_to_end(task.task_id)
                    self._trim()
                self._audit("failed", record, error=str(exc))
            finally:
                self._queue.task_done()

    def _mock(self, task: TaskRequest) -> dict:
        if task.operation == "list_devices":
            if task.driver == "simpleusb":
                return {"output": (
                    "Device [1000] is assigned to device=hw:2,0 card=2\n"
                    "Device [1001] is assigned to device=unassigned card=-1"
                )}
            return {"output": "Device [1002] is assigned to device=hw:3,0 card=3"}
        if task.operation == "reload_driver":
            self._demo_values.update({
                key: value.copy() for key, value in self._demo_defaults.items()
                if key[0] == task.driver
            })
            module = "chan_simpleusb.so" if task.driver == "simpleusb" else "chan_usbradio.so"
            return {"output": f"Module '{module}' reloaded successfully."}
        device_key = task.device or str(task.node_number or "1000")
        values = self._demo_values.setdefault(
            (task.driver, device_key),
            self._demo_defaults.get((task.driver, device_key), {}).copy(),
        )
        if task.operation == "read_settings":
            if task.driver == "simpleusb":
                return {"output": (
                    f"Active radio interface is [{task.device}]\n"
                    "Device String is hw:2,0\n"
                    f"Device Serial is DEMO-SIMPLEUSB-{task.device}\n"
                    "Card is 2\n"
                    f"Rx Level currently set to {values['rx']}\n"
                    f"Tx A Level currently set to {values['txa']}\n"
                    f"Tx B Level current…24182 tokens truncated…Pagination change 26" not in second_page.data
    assert b'aria-current="page">2</a>' in second_page.data

    last_page = client.get("/changes?page=999")
    assert b"Pagination change 5" in last_page.data
    assert b"Pagination change 1" in last_page.data


def test_recent_changes_pagination_bounds_numbered_links(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    sessions = session_factory(settings.database)
    with sessions.begin() as db:
        latest = db.scalar(select(func.max(Change.revision))) or 0
        db.add_all(Change(actor="tester", summary=f"Change {number}",
                          revision=latest + number, details={})
                   for number in range(1, 2001))
    page = client.get("/changes?page=50")
    assert page.status_code == 200
    assert page.data.count(b'class="page-link"') <= 11
    assert b">1</a>" in page.data
    assert b">101</a>" in page.data
    assert "…".encode() in page.data


def test_manual_network_form_previews_and_saves_explicit_service_fields(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated",
                        network_profiles_enabled=True)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    profile = _network_profile("manual.example", "Manual Network",
                               registration_method="iax", iax_registration_server="iax.example.net",
                               iax_registration_port=4568, stats_enabled=True,
                               stats_post_url="https://stats.example.net/update",
                               node_lookup_method="both", dns_node_domain="nodes.example.net",
                               max_dns_node_length=7,
                               external_node_file="/var/lib/asterisk/nodes")
    form = {key: ("true" if value else "false") if isinstance(value, bool) else str(value)
            for key, value in profile.items()}
    preview = client.post("/networks/manual", data=form)
    assert preview.status_code == 200
    assert b"IAX registration server" in preview.data
    assert b"nodes.example.net" in preview.data

    saved = client.post("/networks/manual", data={**form, "action": "commit"})
    assert saved.status_code == 302
    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            network = session.query(Network).filter_by(stable_key="manual.example").one()
            assert network.registration_method == "iax"
            assert network.iax_registration_port == 4568
            assert network.stats_enabled is True
            assert network.stats_post_url == "https://stats.example.net/update"
            assert network.node_lookup_method is None
            assert network.max_dns_node_length == 7
            assert network.external_node_file == "/var/lib/asterisk/nodes"
    finally:
        _dispose(sessions, settings.database)


def test_web_database_backup_and_restore_reverts_later_changes(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    backup = client.get("/backup")
    assert backup.status_code == 200
    backup_bytes = backup.data
    sessions = session_factory(settings.database)
    try:
        with sessions.begin() as session:
            session.add(Node(node_number=9090, name="Temporary node"))
        _dispose(sessions, settings.database)
        restored = client.post("/restore", data={
            "database": (BytesIO(backup_bytes), "backup.sqlite3")
        }, content_type="multipart/form-data")
        assert restored.status_code == 302
        restored_sessions = session_factory(settings.database)
        with restored_sessions() as session:
            assert session.query(Node).filter_by(node_number=9090).count() == 0
            assert session.query(Node).filter_by(node_number=1000).count() == 1
        _dispose(restored_sessions, settings.database)
    finally:
        _dispose(sessions, settings.database)


def test_file_database_restore_replaces_database_and_allows_a_later_write(monkeypatch, tmp_path):
    settings = Settings(database=tmp_path / "manager.sqlite3",
                        writer_allowlist=tmp_path / "writers",
                        secret_key_file=tmp_path / "secret-key")
    settings.writer_allowlist.write_text("writer\n")
    settings.secret_key_file.write_text("test-secret-key")
    upgrade_database(settings.database)
    sessions = session_factory(settings.database)
    with sessions.begin() as db:
        db.add(Node(node_number=9080, name="Backup node"))
    backup = sqlite_snapshot(settings.database)
    try:
        with sessions.begin() as db:
            db.add(Node(node_number=9081, name="Later node"))
        monkeypatch.setattr("asterisk_node_manager.web._request_generation", lambda _settings: None)
        app = create_app(settings)
        app.config.update(TESTING=True)
        client = app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["username"] = "writer"

        restored = client.post("/restore", data={
            "database": (BytesIO(backup.read_bytes()), "backup.sqlite3")
        }, content_type="multipart/form-data")
        assert restored.status_code == 302
        with sessions() as db:
            assert db.query(Node).filter_by(node_number=9080).one().name == "Backup node"
            assert db.query(Node).filter_by(node_number=9081).count() == 0
        with sessions.begin() as db:
            db.add(Node(node_number=9082, name="Post-restore write"))
        with sessions() as db:
            assert db.query(Node).filter_by(node_number=9082).one().name == "Post-restore write"
    finally:
        backup.unlink(missing_ok=True)
        sessions.kw["bind"].dispose()


def test_demo_memory_database_supports_download_and_restore(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")

    backup = client.get("/backup")
    assert backup.status_code == 200
    sessions = session_factory(settings.database)
    with sessions.begin() as session:
        session.add(Node(node_number=9091, name="Temporary memory node"))
    response = client.post("/restore", data={
        "database": (BytesIO(backup.data), "backup.sqlite3")
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with session_factory(settings.database)() as session:
        assert session.query(Node).filter_by(node_number=9091).count() == 0
        assert session.query(Node).filter_by(node_number=1000).count() == 1


def test_advanced_simpleusb_file_editor_saves_known_and_unknown_fields(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    content = "[1000]\nrxmixerset=600\ncustomdriveroption=kept\n\n[1001]\nrxmixerset=501\n"

    preview = client.post("/files/simpleusb.conf", data={"action": "preview", "content": content})
    assert preview.status_code == 200
    committed = client.post("/files/simpleusb.conf", data={
        "action": "commit", "confirmed": "yes", "content": content,
        "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
    })
    assert committed.status_code == 302

    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1000).one()
            assert node.simpleusb_settings.rxmixerset == 600
            custom = session.query(CustomValue).filter_by(
                file_name="simpleusb.conf", section="1000", key="customdriveroption").one()
            assert custom.value == "kept"
    finally:
        _dispose(sessions, settings.database)


def test_advanced_usbradio_file_editor_saves_typed_and_unknown_fields(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    content = "[1000]\nrxdemod=speaker\nrxvoiceadj=0.625\ncustomdriveroption=kept\n"

    preview = client.post("/files/usbradio.conf", data={"action": "preview", "content": content})
    assert preview.status_code == 200
    committed = client.post("/files/usbradio.conf", data={
        "action": "commit", "confirmed": "yes", "content": content,
        "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
    })
    assert committed.status_code == 302

    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1000).one()
            assert node.usbradio_settings.rxdemod == "speaker"
            assert node.usbradio_settings.rxvoiceadj == "0.625"
            custom = session.query(CustomValue).filter_by(
                file_name="usbradio.conf", section="1000", key="customdriveroption").one()
            assert custom.value == "kept"
    finally:
        _dispose(sessions, settings.database)


def test_rpt_editor_uses_submitted_node_defaults_for_overrides(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    sessions = session_factory(settings.database)
    with sessions.begin() as session:
        default = session.query(ConfigValue).filter_by(
            file_name="rpt.conf", section="node-main", key="hangtime").one()
        default.value = "5000"
    content = "[1000]\nhangtime=5000\n[node-main]\nhangtime=6000\n"

    preview = client.post("/files/rpt.conf", data={"action": "preview", "content": content})
    assert preview.status_code == 200
    committed = client.post("/files/rpt.conf", data={
        "action": "commit", "confirmed": "yes", "content": content,
        "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
    })
    assert committed.status_code == 302
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1000).one()
            assert node.hangtime == 5000
    finally:
        _dispose(sessions, settings.database)


def test_rpt_editor_does_not_normalize_against_removed_custom_defaults(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    sessions = session_factory(settings.database)
    with sessions.begin() as session:
        primary = session.query(ConfigValue).filter_by(
            file_name="rpt.conf", section="node-main", key="hangtime").one()
        primary.value = "5000"
        session.add(CustomValue(file_name="rpt.conf", section="node-main", key="hangtime",
                                value="6000", secret=False))
    content = "[1000]\nhangtime=6000\n"

    preview = client.post("/files/rpt.conf", data={"action": "preview", "content": content})
    assert preview.status_code == 200
    committed = client.post("/files/rpt.conf", data={
        "action": "commit", "confirmed": "yes", "content": content,
        "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
    })
    assert committed.status_code == 302
    try:
        with sessions() as session:
            node = session.query(Node).filter_by(node_number=1000).one()
            assert node.hangtime == 6000
        generated = (settings.demo_output_directory / "rpt.conf").read_text()
        assert "hangtime = 6000" in generated
    finally:
        _dispose(sessions, settings.database)


def test_editor_rejects_text_that_differs_from_preview(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    response = client.post("/files/rpt.conf", data={
        "action": "commit", "confirmed": "yes", "preview_hash": "hash-of-earlier-text",
        "content": "[1000]\nhangtime=1234\n",
    })
    assert response.status_code == 400


def test_iax_register_credentials_are_masked_and_preserved_on_save(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    sessions = session_factory(settings.database)
    try:
        with sessions.begin() as session:
            session.add(CustomLine(file_name="iax.conf", section="general", line_number=0,
                                   content="register => demo:secret@host.invalid"))
            session.add(CustomLine(file_name="iax.conf", section="general", line_number=1,
                                   content="register => demo:other@host.invalid"))
        _dispose(sessions, settings.database)
        page = client.get("/files/iax.conf")
        assert b"register =&gt; [hidden]" in page.data
        assert b"secret@host.invalid" not in page.data
        content = ("[general]\n; added comment\nregister => [hidden]\n\n"
                   "; comment between registrations\nregister => [hidden]\n")
        preview = client.post("/files/iax.conf", data={"action": "preview", "content": content})
        assert preview.status_code == 200
        saved = client.post("/files/iax.conf", data={
            "action": "commit", "confirmed": "yes", "content": content,
            "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
        })
        assert saved.status_code == 302
        generated = (settings.demo_output_directory / "iax.conf").read_text()
        assert "register => demo:secret@host.invalid" in generated
        assert "register => demo:other@host.invalid" in generated
        unresolved = "[general]\nregister => [hidden]\nregister => [hidden]\nregister => [hidden]\n"
        preview = client.post("/files/iax.conf", data={"action": "preview", "content": unresolved})
        assert preview.status_code == 200
        response = client.post("/files/iax.conf", data={
            "action": "commit", "confirmed": "yes", "content": unresolved,
            "preview_hash": hashlib.sha256(unresolved.encode()).hexdigest(),
        })
        assert response.status_code == 400
    finally:
        _dispose(sessions, settings.database)


def test_primary_secret_values_are_restored_when_hidden_editor_value_is_unchanged(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    sessions = session_factory(settings.database)
    try:
        with sessions.begin() as db:
            db.add(ConfigValue(file_name="iax.conf", section="general", key="secret",
                               default_value="primary-password", secret=True))
        _dispose(sessions, settings.database)
        page = client.get("/files/iax.conf")
        assert b"secret = [hidden]" in page.data
        content = "[general]\nsecret = [hidden]\n"
        saved = client.post("/files/iax.conf", data={
            "action": "commit", "confirmed": "yes", "content": content,
            "preview_hash": hashlib.sha256(content.encode()).hexdigest(),
        })
        assert saved.status_code == 302
        rendered = (settings.demo_output_directory / "iax.conf").read_text()
        assert "secret = primary-password" in rendered
        assert "secret = [hidden]" not in rendered
    finally:
        _dispose(sessions, settings.database)


def test_login_ignores_external_redirect_and_rejects_oversized_node_number(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    login = client.post("/login?next=https://example.invalid/", follow_redirects=False)
    assert login.headers["Location"] == "/"
    response = client.post("/nodes", data={"node_number": "9223372036854775808", "name": "Too large"})
    assert response.status_code == 400


def test_network_selection_setting_saves_true_value_and_readonly_page_is_safe(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated",
                        network_profiles_enabled=True)
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    assert b"Download backup" not in client.get("/").data
    assert b"Network profiles" in client.get("/").data
    assert client.get("/networks").status_code == 200
    assert client.get("/settings").status_code == 404
    assert b'href="/settings"' not in client.get("/").data
    assert client.post("/settings", data={"network_profiles_enabled": "false"}).status_code == 404
    assert b'name="network_id"' not in client.get("/networks").data
    assert client.post("/settings/default-network", data={"network_id": "1"}).status_code == 404
    enabled = client.post("/settings/network-selection", data={"enabled": "true"})
    assert enabled.status_code == 302
    assert b"Advanced per-node network selection" in client.get("/networks").data
    assert b'name="network_id"' in client.get("/networks").data
    assert client.post("/settings/default-network", data={"network_id": "1"}).status_code == 302
    assert b"Network profiles" in client.get("/").data
    assert b"Download backup" not in client.get("/").data

    sessions = session_factory(settings.database)
    try:
        with sessions() as session:
            assert session.get(Setting, "advanced_node_networks").value == "true"
            assert session.get(Setting, "default_network_key").value == "allstarlink"
        with sessions.begin() as session:
            session.add(Node(node_number=9044, name="Read-only target"))
        _dispose(sessions, settings.database)
        with client.session_transaction() as browser_session:
            browser_session["username"] = "reader"
        page = client.get("/")
        assert page.status_code == 200
        assert b"Read-only target" in page.data
        assert b"Download backup" not in page.data
        assert b"assign_network" not in page.data
    finally:
        _dispose(sessions, settings.database)


def test_backup_restore_has_its_own_menu_page(tmp_path):
    settings = Settings(database=f":memory:{tmp_path.name}", demo_mode=True,
                        demo_output_directory=tmp_path / "generated")
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login")
    assert b"Backup &amp; Restore" in client.get("/").data
    assert b"Download backup" not in client.get("/").data
    page = client.get("/backup-restore")
    assert page.status_code == 200
    assert b"Download backup" in page.data
    assert b"Restore database" in page.data


def test_demo_settings_choose_an_isolated_database_and_explicit_config_must_exist(monkeypatch, tmp_path):
    from asterisk_node_manager.config import load_settings
    monkeypatch.setenv("ASTNODE_WEB__DEMO_MODE", "yes")
    monkeypatch.delenv("ASTNODE_PATHS__DATABASE", raising=False)
    monkeypatch.delenv("ASTNODE_CONFIG", raising=False)
    settings = load_settings()
    assert settings.demo_mode is True
    assert settings.database == ":memory:"

    configured_database = tmp_path / "production.sqlite3"
    config = tmp_path / "demo.toml"
    config.write_text(f'[paths]\ndatabase = "{configured_database}"\n')
    monkeypatch.setenv("ASTNODE_PATHS__DATABASE", str(configured_database))
    assert load_settings(config).database == ":memory:"
    assert not configured_database.exists()
    from asterisk_node_manager.config import Settings
    for database_path in (Settings.database, configured_database):
        with pytest.raises(ValueError, match="in-memory database"):
            create_app(Settings(database=database_path, demo_mode=True,
                                secret_key_file=tmp_path / "missing-secret"))

    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing-explicit-config.toml")


def test_web_main_logs_mode_and_listen_address(monkeypatch, caplog):
    import logging
    import signal
    from asterisk_node_manager import web

    settings = Settings(database=":memory:", demo_mode=True, listen_address="127.0.0.1", port=8765)
    installed_handlers = {}
    monkeypatch.setattr(web, "load_settings", lambda: settings)
    monkeypatch.setattr(web, "create_app", lambda _settings: object())
    monkeypatch.setattr(web, "serve", lambda _app, **_kwargs: None)
    monkeypatch.setattr(web.signal, "signal", lambda signum, handler: installed_handlers.update({signum: handler}))

    with caplog.at_level(logging.INFO):
        assert web.main() == 0

    assert "Starting node-manager web service in demo mode" in caplog.text
    assert "Listening on http://127.0.0.1:8765" in caplog.text
    assert installed_handlers[signal.SIGTERM] is web._handle_shutdown
    assert installed_handlers[signal.SIGINT] is web._handle_shutdown


def test_web_shutdown_handler_exits_for_waitress_to_close(monkeypatch):
    from asterisk_node_manager import web

    with pytest.raises(SystemExit) as exc_info:
        web._handle_shutdown(15, None)
    assert exc_info.value.code == 0
