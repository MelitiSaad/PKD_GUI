"""Revision-aware background task service.

Workers receive immutable snapshots tagged with a document id and exact revision.
Results are only applied after the active document/revision/parameters still match.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Dict, Optional, Tuple
import time
import uuid

import numpy as np


class CancelledTask(Exception):
    pass


class CancellationToken:
    def __init__(self):
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise CancelledTask("background task was cancelled")


@dataclass(frozen=True)
class TaskTag:
    document_id: str
    revision: int
    task_type: str
    params: Tuple[Tuple[str, Any], ...] = ()

    @classmethod
    def make(cls, document_id: str, revision: int, task_type: str, params: Optional[dict] = None) -> "TaskTag":
        return cls(str(document_id), int(revision), str(task_type), tuple(sorted((params or {}).items())))


@dataclass(frozen=True)
class ArraySnapshot:
    document_id: str
    revision: int
    data: np.ndarray
    captured_at: float
    capture_ms: float
    nbytes: int

    @classmethod
    def capture(cls, document_id: str, revision: int, data: np.ndarray) -> "ArraySnapshot":
        start = time.perf_counter()
        arr = np.array(data, copy=True)
        arr.setflags(write=False)
        return cls(str(document_id), int(revision), arr, time.time(), (time.perf_counter() - start) * 1000, int(arr.nbytes))


@dataclass
class TaskHandle:
    id: str
    tag: TaskTag
    token: CancellationToken
    future: Future

    def cancel(self) -> None:
        self.token.cancel()
        self.future.cancel()


@dataclass
class TaskOutcome:
    tag: TaskTag
    status: str
    value: Any = None
    error: Optional[BaseException] = None
    stale_reason: str = ""


@dataclass
class _Spec:
    tag: TaskTag
    work: Callable[[CancellationToken], Any]
    apply: Callable[[Any], None]
    on_error: Optional[Callable[[BaseException], None]]
    latest_only: bool
    handle: Optional[TaskHandle] = None


class BackgroundTaskService:
    """Small bounded scheduler with latest-only coalescing and stale rejection."""
    def __init__(self, executor=None, max_workers: int = 2):
        self.executor = executor or ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pkdqc-bg")
        self.document_id = uuid.uuid4().hex
        self.revision = -1
        self._running: Dict[str, _Spec] = {}
        self._pending: Dict[str, _Spec] = {}
        self._completed: list[tuple[_Spec, Future]] = []
        self._lock = RLock()
        self.outcomes: list[TaskOutcome] = []
        self.last_status = "idle"
        self.closed = False

    def set_document(self, document_id: Optional[str] = None, revision: int = 0) -> str:
        self.cancel_all()
        self.document_id = document_id or uuid.uuid4().hex
        self.revision = int(revision)
        return self.document_id

    def update_revision(self, revision: int) -> None:
        self.revision = int(revision)

    @property
    def queue_size(self) -> int:
        return len(self._running) + len(self._pending)

    def submit_latest(self, tag: TaskTag, work, apply, on_error=None) -> TaskHandle:
        return self._submit(tag, work, apply, on_error, latest_only=True)

    def submit_destructive(self, tag: TaskTag, work, apply, on_error=None) -> TaskHandle:
        return self._submit(tag, work, apply, on_error, latest_only=False)

    def _submit(self, tag: TaskTag, work, apply, on_error, latest_only: bool) -> TaskHandle:
        if self.closed:
            raise RuntimeError("background service is shut down")
        spec = _Spec(tag, work, apply, on_error, latest_only)
        with self._lock:
            if latest_only and tag.task_type in self._running:
                old = self._pending.get(tag.task_type)
                if old and old.handle:
                    old.handle.cancel()
                running = self._running[tag.task_type]
                if running.handle:
                    running.handle.token.cancel()
                token = CancellationToken()
                future = Future()
                handle = TaskHandle(uuid.uuid4().hex, tag, token, future)
                spec.handle = handle
                self._pending[tag.task_type] = spec
                self.last_status = f"queued {tag.task_type}"
                return handle
            return self._start_locked(spec)

    def _start_locked(self, spec: _Spec) -> TaskHandle:
        token = CancellationToken()
        future = self.executor.submit(spec.work, token)
        handle = TaskHandle(uuid.uuid4().hex, spec.tag, token, future)
        spec.handle = handle
        self._running[spec.tag.task_type] = spec
        self.last_status = f"running {spec.tag.task_type}"
        future.add_done_callback(lambda fut, s=spec: self._record_done(s, fut))
        return handle

    def _record_done(self, spec: _Spec, future: Future) -> None:
        with self._lock:
            self._completed.append((spec, future))

    def drain_completed(self) -> list[TaskOutcome]:
        with self._lock:
            items = self._completed
            self._completed = []
        outcomes = []
        for spec, future in items:
            with self._lock:
                self._running.pop(spec.tag.task_type, None)
                pending = self._pending.pop(spec.tag.task_type, None)
                if pending is not None:
                    self._start_locked(pending)
            outcome = self._finish(spec, future)
            self.outcomes.append(outcome)
            outcomes.append(outcome)
        if not self._running and not self._pending:
            self.last_status = "idle"
        return outcomes

    def _finish(self, spec: _Spec, future: Future) -> TaskOutcome:
        tag = spec.tag
        token = spec.handle.token if spec.handle else CancellationToken()
        if token.cancelled or future.cancelled():
            return TaskOutcome(tag, "cancelled")
        try:
            value = future.result()
        except CancelledTask as exc:
            return TaskOutcome(tag, "cancelled", error=exc)
        except BaseException as exc:
            if spec.on_error:
                spec.on_error(exc)
            return TaskOutcome(tag, "error", error=exc)
        stale = self.stale_reason(tag)
        if stale:
            return TaskOutcome(tag, "stale", value=value, stale_reason=stale)
        spec.apply(value)
        return TaskOutcome(tag, "applied", value=value)

    def stale_reason(self, tag: TaskTag) -> str:
        if tag.document_id != self.document_id:
            return "document changed"
        if tag.revision != self.revision:
            return "revision changed"
        return ""

    def cancel_task_type(self, task_type: str) -> None:
        with self._lock:
            for spec in (self._running.get(task_type), self._pending.pop(task_type, None)):
                if spec and spec.handle:
                    spec.handle.cancel()

    def cancel_all(self) -> None:
        with self._lock:
            specs = list(self._running.values()) + list(self._pending.values())
            self._pending.clear()
        for spec in specs:
            if spec.handle:
                spec.handle.cancel()

    def shutdown(self) -> None:
        self.closed = True
        self.cancel_all()
        shutdown = getattr(self.executor, "shutdown", None)
        if shutdown:
            shutdown(wait=False, cancel_futures=True)
