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
                    f"Tx B Level currently set to {values['txb']}"
                )}
            return {"output": (
                f"Active radio interface is [{task.device}]\n"
                "Device String is hw:3,0\n"
                f"Device Serial is DEMO-USBRADIO-{task.device}\n"
                "Card is 3\n"
                "Output A is currently set to voice.\n"
                "Output B is currently set to auxvoice.\n"
                f"Rx Level currently set to {values['rxlevel']}\n"
                f"Rx Squelch currently set to {values['rxsquelch']}\n"
                f"Tx Voice Level currently set to {values['txvoice']}\n"
                f"Tx Tone Level currently set to {values['txtone']}\n"
                f"Current tx limiter setpoint: {values['txslimsp']}"
            )}
        setting = task.setting or ""
        fields = DRIVERS[task.driver].tuning_fields
        if setting not in fields:
            raise OperationError(f"Unsupported {task.driver} tuning setting: {setting}.")
        minimum, maximum = fields[setting]
        if isinstance(task.value, bool) or not isinstance(task.value, int) \
                or not minimum <= task.value <= maximum:
            raise OperationError(f"{setting} must be an integer from {minimum} to {maximum}.")
        if task.driver == "simpleusb":
            values[setting] = task.value
            labels = {"rx": "RX Channel", "txa": "TX Channel A", "txb": "TX Channel B"}
            return {"output": f"Changed setting on {labels[setting]} to {task.value}"}
        values[setting] = task.value
        outputs = {
            "rxsquelch": f"Changed Squelch setting to {task.value}",
            "txvoice": (
                f"Changed txvoice setting on Channel A to {task.value}\n"
                f"Changed Tx Voice Output setting to {task.value}\n"
                f"Tone output starting on channel {task.device}...\n"
                f"Tone output ending on channel {task.device}..."
            ),
            "txtone": f"Changed Tx CTCSS modulation setting to {task.value}",
            "auxvoice": f"Changed auxvoice setting on Channel B to {task.value}",
            "txslimsp": f"Current tx limiter setpoint: {task.value}",
        }
        return {"output": outputs[setting]}

    @staticmethod
    def _temporary_warning(driver: str, setting: str | None) -> str:
        persistent_keys = {
            ("simpleusb", "rx"): "rxmixerset",
            ("simpleusb", "txa"): "txmixaset",
            ("simpleusb", "txb"): "txmixbset",
            ("usbradio", "rxsquelch"): "rxsquelchadj",
            ("usbradio", "txvoice"): "txmixaset or txmixbset, based on the configured output",
            ("usbradio", "txtone"): "txctcssadj",
            ("usbradio", "auxvoice"): "txmixaset or txmixbset, based on the configured output",
        }
        saved_key = persistent_keys.get((driver, setting))
        if saved_key is not None:
            persistence = f" Save the corresponding {saved_key} field in the node's web configuration to persist it."
        else:
            persistence = " This setting has no matching persistent field in the current web app."
        return ("This live change is temporary and is not saved." + persistence +
                " It remains live until an Asterisk reload is requested, which will revert the unsaved change.")

    def _expire(self) -> None:
        cutoff = self.clock() - TASK_TTL_SECONDS
        with self._lock:
            for task_id, record in list(self._tasks.items()):
                if record["status"] in {"succeeded", "failed"} and record["_updated_monotonic"] < cutoff:
                    del self._tasks[task_id]

    def _trim(self) -> None:
        completed = sum(record["status"] in {"succeeded", "failed"}
                        for record in self._tasks.values())
        if completed <= TASK_CAPACITY:
            return
        for task_id, record in list(self._tasks.items()):
            if completed <= TASK_CAPACITY:
                break
            if record["status"] in {"succeeded", "failed"}:
                del self._tasks[task_id]
                completed -= 1

    @staticmethod
    def _public(record: dict) -> dict:
        return {key: value for key, value in record.items()
                if key not in {"actor", "_updated_monotonic"}} | {
                    "created_at": record["created_at"], "updated_at": record["updated_at"]}

    @staticmethod
    def _audit(event: str, record: dict, **extra) -> None:
        payload = {
            "event": "asterisk_live_operation",
            "task_id": record["task_id"],
            "actor": record["actor"],
            "node_number": record["node_number"],
            "driver": record["driver"],
            "operation": record["operation"],
            "status": event,
            **extra,
        }
        logger.info("%s", json.dumps(payload, separators=(",", ":"), sort_keys=True))
