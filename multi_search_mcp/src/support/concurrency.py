"""Bounded daemon worker pool for deadline-driven provider calls."""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable


_STOP = object()


class BoundedDaemonExecutor:
    """Run at most ``max_workers`` tasks without blocking process exit.

    Python cannot safely cancel a running thread. The pool therefore bounds
    timed-out work instead: a task keeps its slot until it returns, and later
    submissions wait only until their request deadline. Workers are daemon
    threads so a stuck provider cannot hold the MCP process open at shutdown.
    """

    def __init__(self, *, max_workers: int, thread_name_prefix: str):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._max_workers = max_workers
        self._thread_name_prefix = thread_name_prefix
        self._tasks: queue.Queue = queue.Queue()
        self._slots = threading.BoundedSemaphore(max_workers)
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._idle_workers = 0
        self._queued_tasks = 0
        self._shutdown = False

    def submit_before(
        self,
        deadline: float,
        fn: Callable[..., Any],
        /,
        *args,
        **kwargs,
    ) -> Future | None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._slots.acquire(timeout=remaining):
            return None

        future = Future()
        with self._lock:
            if self._shutdown:
                self._slots.release()
                raise RuntimeError("cannot schedule new futures after shutdown")
            self._queued_tasks += 1
            self._tasks.put((future, fn, args, kwargs))
            self._start_worker_if_needed()
        return future

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._lock:
            if self._shutdown:
                threads = list(self._threads)
            else:
                self._shutdown = True
                threads = list(self._threads)

        if cancel_futures:
            self._cancel_queued_tasks()
        for _ in threads:
            self._tasks.put(_STOP)
        if wait:
            for thread in threads:
                thread.join()

    def _start_worker_if_needed(self) -> None:
        if (
            self._queued_tasks <= self._idle_workers
            or len(self._threads) >= self._max_workers
        ):
            return
        index = len(self._threads)
        worker = threading.Thread(
            target=self._worker,
            name=f"{self._thread_name_prefix}-{index}",
            daemon=True,
        )
        self._threads.append(worker)
        worker.start()

    def _worker(self) -> None:
        while True:
            with self._lock:
                self._idle_workers += 1
            task = self._tasks.get()
            with self._lock:
                self._idle_workers -= 1
                if task is not _STOP:
                    self._queued_tasks -= 1
            try:
                if task is _STOP:
                    return
                future, fn, args, kwargs = task
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    future.set_result(fn(*args, **kwargs))
                except BaseException as exc:
                    future.set_exception(exc)
            finally:
                if task is not _STOP:
                    self._slots.release()
                self._tasks.task_done()

    def _cancel_queued_tasks(self) -> None:
        while True:
            try:
                task = self._tasks.get_nowait()
            except queue.Empty:
                return
            try:
                if task is _STOP:
                    continue
                future, _fn, _args, _kwargs = task
                with self._lock:
                    self._queued_tasks -= 1
                future.cancel()
                self._slots.release()
            finally:
                self._tasks.task_done()
