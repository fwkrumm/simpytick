"""Sleep-based waiting with optional cooperative cancellation."""

import math
import threading
import time


def sleep(
    seconds: float,
    *,
    stop_event: threading.Event | None = None,
    check_interval: float = 0.01,
) -> bool:
    """Sleep for seconds; return True if stopped, False if the wait completes.

    seconds must be finite and nonnegative. check_interval must be finite and
    positive; it limits each sleep chunk when stop_event is supplied. An active
    sleep cannot be interrupted, and OS scheduling can delay cancellation beyond
    check_interval. Without stop_event, use a single time.sleep() call.

    Monotonic deadlines account for chunk overhead, but do not guarantee exact
    wake-up times or compensate for work between separate calls.
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("seconds must be finite and nonnegative")
    if not math.isfinite(check_interval) or check_interval <= 0:
        raise ValueError("check_interval must be finite and positive")
    if stop_event is None:
        time.sleep(seconds)
        return False

    deadline = time.monotonic() + seconds
    while not stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(remaining, check_interval))
    return True