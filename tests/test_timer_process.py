"""Exercise real spawned timer startup, failure reporting, and cleanup."""

import os
import unittest
from unittest.mock import patch

from simpytick.timer import TimedEvent


def _fail_timer(*_args, **_kwargs):
    raise ValueError("broken process worker")


def _exit_timer(*_args, **_kwargs):
    os._exit(3)


class TestTimerProcess(unittest.TestCase):
    """Verify real spawn startup, tick delivery, and process cleanup."""

    def test_spawned_worker_emits_ticks_and_is_reaped(self):
        """Timing runs in a real child without mocking process configuration."""
        with TimedEvent(s=0.05, n=3, compensation=False) as context:
            self.assertEqual(list(context), [0, 1, 2])
        self.assertFalse(context._worker.is_alive())  # pylint: disable=protected-access
        self.assertIsNotNone(context._worker.exitcode)  # pylint: disable=protected-access

    def test_spawned_worker_exception_reaches_consumer(self):
        """A serializable status reports child exceptions without a configured logger."""
        with patch("simpytick.timer.timer", _fail_timer):
            with self.assertRaisesRegex(RuntimeError, "ValueError: broken process worker"):
                with TimedEvent(s=60, n=-1) as context:
                    list(context)
        self.assertFalse(getattr(context, "_worker").is_alive())

    def test_abrupt_exit_is_not_silent(self):
        """An exit that bypasses status reporting raises with its exit code."""
        with patch("simpytick.timer.timer", _exit_timer):
            with self.assertRaisesRegex(RuntimeError, "exitcode=3"):
                with TimedEvent(s=60, n=-1) as context:
                    list(context)
        self.assertFalse(getattr(context, "_worker").is_alive())
