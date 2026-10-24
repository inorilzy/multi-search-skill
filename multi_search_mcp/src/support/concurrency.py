"""Bounded daemon worker pool for deadline-driven provider calls."""
from __future__ import annotations

import os
import queue
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import Any, Callable


_STOP = object()


def pool_size_from_env(name: str, default: int, minimum: int = 1) -> int:
    """Read a positive integer pool capacity from the environment."""
    text = os.environ.get(name, "").strip()
    try:
        value = int(text)
    except ValueError:
        return max(minimum, int(default))
    return max(minimum, value)


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

        return self._submit_acquired(fn, *args, **kwargs)

    def submit_nowait(self, fn: Callable[..., Any], /, *args, **kwargs) -> Future | None:
        """Admit work without blocking the caller or queuing beyond capacity."""
        if not self._slots.acquire(blocking=False):
            return None
        return self._submit_acquired(fn, *args, **kwargs)

    def _submit_acquired(self, fn: Callable[..., Any], /, *args, **kwargs) -> Future:
        future = Future()
        with self._lock:
            if self._shutdown:
                self._slots.release()
                raise RuntimeError("cannot schedule new futures after shutdown")
            self._queued_tasks += 1
            self._tasks.put((future, fn, args, kwargs))
            self._start_worker_if_needed()
        return future

    def run_all_before(
        self,
        deadline: float,
        fn: Callable[[Any], Any],
        items,
        *,
        on_admission_failure: Callable[[Any], Any],
    ) -> dict:
        """Run ``fn`` for every item, admitting work until ``deadline``.

        Mimics a bounded ``ThreadPoolExecutor.map`` without extending the
        deadline: items are submitted one at a time (blocking at most until
        ``deadline`` for a free slot) and completed futures are collected as
        they finish. An item that cannot be admitted before the deadline gets
        ``on_admission_failure(item)`` instead of being run.

        Returns ``{id(item): result}``. Exceptions propagate as the item's
        result so callers can translate them at their own boundary.

        This is a *single-layer* primitive. Nested fan-out must use a separate
        executor instance per layer: a parent task waiting for children on the
        same pool can hold every slot and deadlock.
        """
        results: dict[int, Any] = {}
        pending: dict[Future, Any] = {}
        remaining = list(items)
        while remaining or pending:
            while remaining:
                item = remaining.pop(0)
                future = self.submit_before(deadline, fn, item)
                if future is None:
                    results[id(item)] = on_admission_failure(item)
                    continue
                pending[future] = item
            if not pending:
                break
            timeout = max(0.0, deadline - time.monotonic())
            if timeout <= 0:
                # Admission is closed. Only already-finished work can be
                # collected without blocking; anything still running keeps its
                # slot but must not hold the caller past the deadline.
                break
            done, _ = wait(tuple(pending), timeout=timeout, return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                item = pending.pop(future)
                try:
                    results[id(item)] = future.result()
                except Exception as exc:  # task boundary
                    results[id(item)] = exc
        for future, item in pending.items():
            if future.done():
                try:
                    results[id(item)] = future.result()
                except Exception as exc:  # task boundary
                    results[id(item)] = exc
            else:
                future.cancel()
                results[id(item)] = on_admission_failure(item)
        return results

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

    @staticmethod
    def _execute_task(task) -> None:
        future, fn, args, kwargs = task
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)

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
                self._execute_task(task)
            finally:
                if task is not _STOP:
                    self._slots.release()
                task = None
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
