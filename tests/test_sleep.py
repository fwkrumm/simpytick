"""Verify public sleep completion, cancellation, and parameter validation."""

import threading
import unittest
from importlib import import_module
from unittest.mock import call, patch

import simpytick

sleep_module = import_module("simpytick.sleep")


class TestSleep(unittest.TestCase):
    """Exercise sleep without real delays or background workers."""

    def test_without_stop_event_uses_single_sleep(self):
        """An ordinary wait delegates once, including for zero seconds."""
        with patch.object(sleep_module.time, "sleep") as sleep:
            self.assertFalse(simpytick.sleep(0.25))
            self.assertFalse(simpytick.sleep(0))
        self.assertEqual(sleep.call_args_list, [call(0.25), call(0)])

    def test_stop_request_prevents_sleep(self):
        """An already set stop event cancels immediately."""
        stop = threading.Event()
        stop.set()
        with patch.object(sleep_module.time, "sleep") as sleep:
            self.assertTrue(simpytick.sleep(60, stop_event=stop))
        sleep.assert_not_called()

    def test_custom_check_interval_limits_sleep_chunk(self):
        """A stop request during the first custom chunk prevents further sleeps."""
        stop = threading.Event()
        with patch.object(sleep_module.time, "monotonic", return_value=0), patch.object(
            sleep_module.time, "sleep", side_effect=lambda seconds: stop.set()
        ) as sleep:
            self.assertTrue(simpytick.sleep(60, stop_event=stop, check_interval=0.005))
        sleep.assert_called_once_with(0.005)

    def test_deadline_accounts_for_sleep_overhead(self):
        """Chunk overhead reduces the remaining wait instead of accumulating."""
        with patch.object(
            sleep_module.time, "monotonic", side_effect=[0, 0, 0.02, 0.025]
        ), patch.object(sleep_module.time, "sleep") as sleep:
            self.assertFalse(simpytick.sleep(0.025, stop_event=threading.Event()))
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(sleep.call_args_list[0], call(0.01))
        self.assertAlmostEqual(sleep.call_args_list[1].args[0], 0.005)

    def test_invalid_parameters_raise_before_sleeping(self):
        """Negative or nonfinite durations and invalid check intervals fail early."""
        with patch.object(sleep_module.time, "sleep") as sleep:
            for seconds in (-1, float("nan"), float("inf"), -float("inf")):
                with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, "seconds"):
                    simpytick.sleep(seconds)
            for interval in (0, -1, float("nan"), float("inf"), -float("inf")):
                with self.subTest(interval=interval), self.assertRaisesRegex(
                    ValueError, "check_interval"
                ):
                    simpytick.sleep(1, check_interval=interval)
                sleep.assert_not_called()
