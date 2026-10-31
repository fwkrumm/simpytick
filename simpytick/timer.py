"""
High-precision periodic timer backed by a ``multiprocessing.Process``.

Public surface:
- :func:`timer` --- fire an event *n* times at interval *s*.
- :class:`TimedEvent` --- context manager that iterates once per tick.
"""
import itertools
import logging
import math
import multiprocessing
import threading
import time
from multiprocessing import synchronize
from typing import Literal, Union

from simpytick._worker import run_worker
from simpytick.logger import get_logger
from simpytick.sleep import sleep

# Spawn prevents child code from retaining copied parent state. On POSIX its
# launcher may still briefly fork, so use TimedEvent(backend="thread") after
# libraries such as gRPC have started threads or opened poller descriptors.
_SPAWN_CONTEXT = multiprocessing.get_context("spawn")


def _validate_timer(n: int, s: float) -> None:
    """Reject invalid cycle counts and periods before starting any work."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an integer")
    if n < -1:
        raise ValueError("n must be -1 or nonnegative")
    if isinstance(s, bool) or not isinstance(s, (int, float)):
        raise TypeError("s must be a real number")
    if not math.isfinite(s) or s <= 0:
        raise ValueError("s must be finite and positive")


def _cycles(n: int):
    """Yield cycle indices; runs indefinitely when n == -1."""
    if n == -1:
        yield from itertools.count()
    else:
        yield from range(n)


def _wait_for_next_tick(duration: float, stop_event: threading.Event = None) -> bool:
    """Wait for one interval; return whether thread shutdown was requested.

    With a stop event, sleep in chunks of at most 10 ms and check for shutdown
    between chunks. An active sleep cannot be interrupted; OS scheduling may
    delay shutdown further. Monotonic deadlines avoid accumulating chunk overhead.
    This avoids potentially coarse Event.wait() timeouts on Windows and other
    platforms, but does not guarantee precise wake-up times.
    """
    return sleep(duration, stop_event=stop_event)


def _tick(period: float, enable_compensation: bool):
    """Yield monotonic deadline waits, or fixed waits without compensation."""
    # Inspired by watsonic's generator-based periodic scheduling:
    # https://stackoverflow.com/questions/8600161/executing-periodic-actions
    # https://stackoverflow.com/users/watsonic
    if not enable_compensation:
        while True:
            yield period

    next_tick = time.monotonic()
    while True:
        next_tick += period
        yield max(next_tick - time.monotonic(), 0.0)


def timer(  # pylint: disable=too-many-arguments
    n: int,
    s: float,
    event: Union[synchronize.Event, threading.Event],
    enable_compensation: bool = True,
    logger_level: int = None,
    *,
    stop_event: threading.Event = None,
):
    """
    Timer function that sets an event periodically.

    Args:
        n: Nonnegative number of cycles, or -1 to run indefinitely.
        s: Finite, positive timing interval in seconds.
        event: multiprocessing.synchronize.Event or threading.Event which will be set periodically
            based on the timing interval. The event is expected to be cleared by the caller
            after each tick.
        enable_compensation: Maintain accumulated monotonic deadlines to correct drift.
            Late cycles shorten the next wait, down to zero while catching up.
            When disabled, each tick is followed by a fixed interval wait.
        stop_event: Optional thread-backend event used to request an early stop.

    The first tick fires immediately. Prints warning if event is still set
    from the previous cycle (timer overrun). Zero cycles returns without ticks.
    """
    _validate_timer(n, s)
    if logger_level is not None:
        process_logger = get_logger("timer", console_log_level=logger_level, file_log_level=None)
    else:
        process_logger = None

    ticks = _tick(s, enable_compensation)
    for i in _cycles(n):
        if stop_event is not None and stop_event.is_set():
            break

        event.set()

        sleep_duration = next(ticks)
        if _wait_for_next_tick(sleep_duration, stop_event):
            break

        if event.is_set():
            # not optimal but using log callback here would require passing a logger to the
            # timer function and we want to avoid that for now
            if process_logger:
                process_logger.warning(
                    "Warning: Timer overrun at cycle %d. Event is still set.", i + 1
                )

class TimedEvent:  # pylint: disable=too-many-instance-attributes
    """
    Context manager that drives periodic task execution using the existing
    timer function.

    Usage::

        with TimedEvent(s=0.01, n=100) as te:
            for tick in te:
                # executed exactly n times, once per timer tick

    Parameters
    ----------
    s : float
        Period time in seconds between ticks.
    n : int
        Number of ticks (cycles) to run.
    backend : {"process", "thread"}
        ``"process"`` preserves process-isolated timing. ``"thread"`` avoids
        creating a child after libraries such as gRPC have started threads.

    Notes
    -----
    The timer runs in either a spawn-isolated daemon process or a daemon thread.
    Workers retain normal OS priority. Exiting the context stops and joins the
    worker. Iteration raises RuntimeError if a background worker fails.
    """

    def __init__(
        self,
        s: float,
        n: int,
        compensation: bool = True,
        logger: logging.Logger | logging.LoggerAdapter | None = None,
        backend: Literal["process", "thread"] = "process",
    ):
        _validate_timer(n, s)
        if backend not in ("process", "thread"):
            raise ValueError(f"Unsupported timer backend: {backend}")
        self.s = s
        self.n = n
        self.compensation = compensation
        self._event = (
            threading.Event() if backend == "thread" else _SPAWN_CONTEXT.Event()
        )
        self._stop_event = threading.Event()
        self._worker: multiprocessing.Process | threading.Thread | None = None
        self._status_reader = None
        self._status_writer = None
        self._worker_result = None
        self._backend = backend
        self.overrun_count: int = 0  # number of cycles where task exceeded the tick period
        self.logger = logger

    def __enter__(self) -> "TimedEvent":
        """Start a normal-priority worker, cleaning up if startup fails."""
        timer_args = (
            self.n,
            self.s,
            self._event,
        )
        timer_kwargs = {
            "enable_compensation": self.compensation,
            "logger_level": self.logger.getEffectiveLevel() if self.logger else None,
            "stop_event": self._stop_event if self._backend == "thread" else None,
        }
        self._status_reader, self._status_writer = _SPAWN_CONTEXT.Pipe(duplex=False)
        try:
            worker_type = (
                threading.Thread if self._backend == "thread" else _SPAWN_CONTEXT.Process
            )
            self._worker = worker_type(
                target=run_worker,
                args=(timer, timer_args, timer_kwargs, self._status_writer),
                daemon=True,
            )
            self._worker.start()
            if self._backend == "process":
                self._status_writer.close()
        except BaseException as error:
            try:
                started = self._worker is not None and (
                    self._worker.ident is not None if self._backend == "thread"
                    else self._worker.pid is not None
                )
                if started:
                    self.__exit__(type(error), error, error.__traceback__)
            finally:
                self._close_status()
            raise
        return self

    def _close_status(self) -> None:
        for connection in (self._status_reader, self._status_writer):
            if connection is not None:
                connection.close()
        self._status_reader = self._status_writer = None

    def _check_worker_error(self) -> None:
        if self._worker_result is None and self._status_reader is not None:
            try:
                if self._status_reader.poll():
                    self._worker_result = self._status_reader.recv()
            except (EOFError, BrokenPipeError):
                pass
        if self._worker_result is not None and self._worker_result[0] == "error":
            raise RuntimeError(f"Timer worker failed: {self._worker_result[1]}")

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Stop and join the worker and close its status connections."""
        try:
            if self._worker is not None:
                if self._backend == "process":
                    if self._worker.is_alive():
                        self._worker.terminate()
                else:
                    self._stop_event.set()
                self._worker.join()
                if exc_type is None:
                    self._check_worker_error()
        finally:
            self._close_status()
        return False  # do not suppress exceptions

    def __iter__(self):
        """
        Yield the cycle index (0-based) once per timer tick.

        Each iteration waits for the timer to set the event, then clears it
        before yielding, so the task code runs synchronously between ticks.

        After each yield (i.e. after the task body has finished), the event
        is checked again.  If it is already set the timer has fired the next
        tick while the task was still running --- a timer overrun.  A warning
        is printed and ``self.overrun_count`` is incremented.

        Deadlock prevention
        -------------------
        ``threading.Event.set()`` is idempotent: if the task overruns by more
        than one tick, several timer fires collapse into a single set signal.
        ``__iter__`` would then wait forever on a tick that the (now-finished)
        timer thread will never fire.  To guard against this, every wait uses a
        timeout capped at 100 ms. Normal completion with collapsed ticks stops
        iteration early; worker failures raise RuntimeError, even without a logger.
        """
        try:
            i = 0
            while self.n == -1 or i < self.n:
                self._check_worker_error()
                while not self._event.wait(timeout=min(self.s, 0.1)):
                    self._check_worker_error()
                    if not self._worker.is_alive():
                        self._worker.join()
                        self._check_worker_error()
                        if self._worker_result != ("done", None):
                            exitcode = getattr(self._worker, "exitcode", None)
                            raise RuntimeError(
                                f"Timer worker exited without completion (exitcode={exitcode})"
                            )
                        if self._event.is_set():
                            break
                        if self.logger:
                            self.logger.warning(
                                "Timer process ended after %d ticks; %d tick(s) missed.",
                                i,
                                self.n - i,
                            )
                        return
                    self._check_worker_error()
                self._event.clear()
                yield i
                i += 1
                # Stop after n ticks (mirrors the timer process cycle count).
                # Checked here --- after the task body returns --- so the last
                # yield is never skipped even if the process has already exited.
                if self.n != -1 and i >= self.n:
                    return
        except KeyboardInterrupt:
            if self.logger:
                self.logger.info("strg+c")
            raise  # re-raise so the caller's signal handling is not suppressed
        # cleanup is handled solely by __exit__ (terminate + join)


if __name__ == "__main__":

    demo_logger = get_logger("timer_demo")
    demo_logger.info("Starting timer demo with compensation enabled...")

    with TimedEvent(s=0.01, n=10, compensation=True, logger=demo_logger) as te:
        for tick in te:
            demo_logger.info("Tick %d at %s", tick, time.time())
            time.sleep(2.1)
