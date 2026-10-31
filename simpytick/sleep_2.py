"""Automatically drift-compensated sleeping without background workers.

Exported as simpytick.sleep_2, CompensatedSleep always enables compensation;
there is no compensation switch. Create one instance before a loop and reuse
it on every iteration. Creating an instance inside the loop discards its
schedule and prevents compensation across iterations. For independent,
uncompensated waits, use simpytick.sleep() instead.
"""

import math
import threading
import time

from simpytick.sleep import sleep


class CompensatedSleep:
    """Callable sleeper with automatic, always-active drift compensation.

    Reuse the same instance across calls: create it once outside the loop.
    Recreating it each iteration loses the state required for compensation.
    There is no flag to enable compensation; it is always active. Use one
    instance per loop and do not share an instance across threads.

    The schedule starts on the first call. Each call advances the deadline by
    seconds, accounting for work and oversleep since previous calls. Missed
    deadlines produce zero waits until caught up; exact timing is not guaranteed.
    reset() or cancellation clears the schedule; the next call starts a new one.

    Example::

        from simpytick import sleep_2

        sleep = sleep_2()
        for _ in range(100):
            sleep(0.01)
    """

    def __init__(self):
        self._deadline: float | None = None

    def reset(self) -> None:
        """Discard the schedule so the next call starts a new one."""
        self._deadline = None

    def __call__(
        self,
        seconds: float,
        *,
        stop_event: threading.Event | None = None,
        check_interval: float = 0.01,
    ) -> bool:
        """Wait for the next deadline; return True on cancellation, else False.

        seconds must be finite and nonnegative; check_interval must be finite
        and positive. Cancellation resets the schedule. Invalid arguments leave
        it unchanged. Stop checks have the same latency limits as simpytick.sleep.
        """
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("seconds must be finite and nonnegative")
        if not math.isfinite(check_interval) or check_interval <= 0:
            raise ValueError("check_interval must be finite and positive")
        if stop_event is not None and stop_event.is_set():
            self.reset()
            return True

        now = time.monotonic()
        self._deadline = (now if self._deadline is None else self._deadline) + seconds
        interrupted = sleep(
            max(self._deadline - now, 0.0),
            stop_event=stop_event,
            check_interval=check_interval,
        )
        if interrupted:
            self.reset()
        return interrupted
