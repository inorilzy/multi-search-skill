"""Bounded daemon worker pool for deadline-driven provider calls."""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable


_STOP = object()


class BoundedDaemonExecutor:
    """Run at most ``max_workers`` admitted tasks without blocking process exit.

    Python cannot safely cancel a running thread. A caller whose deadline has
    passed therefore *abandons* its future: queued work is cancelled, and a
    running task is detached so its admission slot is returned immediately and
    new requests are not stuck behind it. Detached tasks keep running on their
    own thread until they return; at most ``max_detached`` of them may exist at
    once, so the thread count stays bounded by ``max_workers + max_detached``.
    Once that budget is spent an abandoned task keeps its slot, and admission
    reports saturation (``None``) instead of creating more threads. Workers are
    daemon threads so a stuck provider cannot hold the process open at exit.
    """

    def __init__(
        self, *, max_workers: int, thread_name_prefix: str, max_detached: int | None = None,
    ):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_detached is None:
            max_detached = max_workers
        if max_detached < 0:
            raise ValueError("max_detached must not be negative")
        self._max_workers = max_workers
        self._max_detached = max_detached
        self._thread_name_prefix = thread_name_prefix
        self._tasks: queue.Queue = queue.Queue()
        self._slots = threading.BoundedSemaphore(max_workers)
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._idle_workers = 0
        self._queued_tasks = 0
        self._running: dict[Future, bool] = {}
        self._detached = 0
        self._shutdown = False

    @property
    def detached_count(self) -> int:
        """Abandoned tasks still running without holding an admission slot."""
        with self._lock:
            return self._detached

    def abandon(self, future: Future) -> bool:
        """Stop ``future`` from holding capacity once its caller has given up.

        Returns ``True`` when the slot no longer blocks new work: the future
        was cancelled before it started, already finished, or was detached.
        Returns ``False`` when the detached budget is exhausted, in which case
        the running task keeps its slot until it returns.
        """
        if future.cancel() or future.done():
            return True
        with self._lock:
            if future not in self._running:
                # Finished between the checks above and taking the lock.
                return True
            if self._running[future]:
                return True
            if self._detached >= self._max_detached:
                return False
            self._running[future] = True
            self._detached += 1
        self._slots.release()
        return True

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
        # Admitted tasks never exceed max_workers and detached ones never
        # exceed max_detached, so this many threads can always serve the queue.
        if (
            self._queued_tasks <= self._idle_workers
            or len(self._threads) >= self._max_workers + self._max_detached
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

    def _execute_task(self, task) -> None:
        future, fn, args, kwargs = task
        with self._lock:
            # Register before the future can be observed as running, so that
            # abandon() always finds a running task here.
            self._running[future] = False
        if not future.set_running_or_notify_cancel():
            with self._lock:
                self._running.pop(future, None)
            self._slots.release()
            return
        result = None
        failure: BaseException | None = None
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the future
            failure = exc
        # Return the admission slot *before* publishing the result. Setting the
        # result first let a caller that immediately submits the next task find
        # every permit taken by work that had already finished, which surfaced
        # as a spurious "capacity exhausted" under a burst of ranked fetches.
        with self._lock:
            detached = self._running.pop(future, False)
            if detached:
                self._detached -= 1
        if not detached:
            self._slots.release()
        if failure is not None:
            future.set_exception(failure)
        else:
            future.set_result(result)

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


POOL_SATURATED_ERROR_TYPE = "capacity"


def pool_saturated_message(pool_name: str, budget: float) -> str:
    """Describe a request that never obtained a worker slot.

    The wording deliberately avoids "timeout"/"deadline" so text-based error
    classifiers (key health, site memory) never mistake local saturation for a
    slow provider or target.
    """
    return f"{pool_name} worker pool saturated: no free slot within {budget}s"
