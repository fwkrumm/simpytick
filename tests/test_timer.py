"""Unit tests for simpytick/timer.py public API."""
import inspect
import threading
import unittest
from unittest.mock import Mock, patch

from simpytick.timer import TimedEvent, timer


class TestTimedEvent(unittest.TestCase):
    """Ensure TimedEvent class is directly constructible."""

    def test_timed_event_instance_creation(self):
        """TimedEvent constructor returns a TimedEvent context manager instance."""
        timer_ctx = TimedEvent(s=0.01, n=1, compensation=False)
        self.assertIsInstance(timer_ctx, TimedEvent)

    def test_thread_backend_emits_all_ticks(self):
        """Thread backend emits requested ticks without creating a process."""
        with TimedEvent(s=0.01, n=3, compensation=False, backend="thread") as timer_ctx:
            self.assertEqual(list(timer_ctx), [0, 1, 2])


class TestTimer(unittest.TestCase):
    """Ensure low-level timer keeps its established positional API."""

    def test_only_stop_event_is_keyword_only(self):
        """New shutdown event must not expand positional API."""
        parameters = inspect.signature(timer).parameters

        self.assertEqual(
            parameters["enable_compensation"].kind,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        self.assertEqual(
            parameters["logger_level"].kind,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        self.assertEqual(parameters["stop_event"].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_existing_five_positional_arguments_remain_valid(self):
        """Established positional arguments still invoke timer unchanged."""
        tick_event = threading.Event()

        timer(0, 0.01, tick_event, False, None)


class TestTimerValidation(unittest.TestCase):
    """Both public entry points reject invalid arguments before starting work."""

    def test_invalid_periods_fail_before_event_or_worker_creation(self):
        """Zero, negative, nonfinite, and nonnumeric periods cannot start a timer."""
        for period in (0, -0.01, float("nan"), float("inf"), -float("inf"), None, "1", True):
            error = TypeError if period is None or isinstance(period, (str, bool)) else ValueError
            with self.subTest(period=period), patch("simpytick.timer._SPAWN_CONTEXT") as spawn:
                event = Mock()
                with self.assertRaises(error):
                    TimedEvent(s=period, n=1)
                with self.assertRaises(error):
                    timer(1, period, event)
                spawn.Event.assert_not_called()
                spawn.Process.assert_not_called()
                event.set.assert_not_called()

    def test_invalid_counts_fail_before_event_or_worker_creation(self):
        """Counts must be integers greater than or equal to -1, excluding booleans."""
        for count in (-2, 1.5, None, "1", True):
            error = ValueError if count == -2 else TypeError
            with self.subTest(count=count), patch("simpytick.timer._SPAWN_CONTEXT") as spawn:
                event = Mock()
                with self.assertRaises(error):
                    TimedEvent(s=0.01, n=count)
                with self.assertRaises(error):
                    timer(count, 0.01, event)
                spawn.Event.assert_not_called()
                event.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
