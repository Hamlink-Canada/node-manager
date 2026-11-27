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

from .registry import execute_operation


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


class LiveTaskQueue:
    def __init__(self, asterisk_socket: Path, demo_mode: bool = False,
                 clock: Callable[[], float] = time.monotonic):
        self.asterisk_socket = asterisk_socket
        self.demo_mode = demo_mode
        self.clock = clock
        self._queue: queue.Queue[TaskRequest] = queue.Queue(maxsize=QUEUE_CAPACITY)
        self._tasks: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()
        self._thread = threading.Thread(target=self._work, name="asterisk-live-operations", daemon=True)
        self._thread.start()

    def submit(self, actor: str, driver: str, operation: str, node_number: int | None,
               device: str | None, setting: str | None, value: object) -> dict:
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
        task = TaskRequest(task_id, actor, driver, operation, node_number, device, setting, value)
        with self._lock:
            try:
                self._queue.put_nowait(task)
            except queue.Full as exc:
                raise queue.Full("Live operation queue is full; retry shortly.") from exc
            self._tasks[task_id] = record
            self._trim()
        self._audit("queued", record)
        return self._public(record)

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

    @staticmethod
    def _mock(task: TaskRequest) -> dict:
        if task.operation == "list_devices":
            return {"output": f"Demo {task.driver} interface: demo-device (Node {task.node_number or 'unassigned'})"}
        if task.operation == "read_settings":
            values = ("rx=500, txa=500, txb=500" if task.driver == "simpleusb"
                      else "rxsquelch=500, txvoice=500, txtone=500, auxvoice=500, txslimsp=9000")
            return {"output": f"Demo tuning settings: {values}"}
        return {"output": f"Demo only: {task.driver} {task.setting} would be set to {task.value}; no Asterisk connection was made."}

    @staticmethod
    def _temporary_warning(driver: str, setting: str | None) -> str:
        persistent_keys = {
            ("simpleusb", "rx"): "rxmixerset",
            ("simpleusb", "txa"): "txmixaset",
            ("simpleusb", "txb"): "txmixbset",
            ("usbradio", "rxsquelch"): "rxsquelchadj",
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
