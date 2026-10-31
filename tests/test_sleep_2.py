"""Deterministic checks for stateful compensated sleeping."""

import threading
import unittest
from importlib import import_module
from unittest.mock import patch

import simpytick

sleep_module = import_module("simpytick.sleep_2")


class TestCompensatedSleep(unittest.TestCase):
    """Verify deadline persistence without sleeping or starting workers."""

    def test_deadlines_compensate_and_catch_up(self):
        """Work and oversleep shorten later waits, including zero waits."""
        sleeper = simpytick.sleep_2()
        with patch.object(
            sleep_module.time, "monotonic", side_effect=[0, 0.1875, 0.5, 0.5, 0.5]
        ), patch.object(sleep_module, "sleep", return_value=False) as wait:
            for _ in range(5):
                self.assertFalse(sleeper(0.125))
        self.assertEqual(
            [entry.args[0] for entry in wait.call_args_list],
            [0.125, 0.0625, 0, 0, 0.125],
        )

    def test_reset_and_instances_start_independent_schedules(self):
        """Reset discards old deadlines; instances never share state."""
        first = simpytick.sleep_2()
        second = simpytick.sleep_2()
        with patch.object(
            sleep_module.time, "monotonic", side_effect=[0, 10, 20]
        ), patch.object(sleep_module, "sleep", return_value=False) as wait:
            first(0.125)
            second(0.125)
            first.reset()
            first(0.125)
        self.assertEqual([entry.args[0] for entry in wait.call_args_list], [0.125] * 3)

    def test_cancellation_resets_and_forwards_stop_parameters(self):
        """An interrupted wait discards its deadline before reuse."""
        sleeper = simpytick.sleep_2()
        stop = threading.Event()
        with patch.object(
            sleep_module.time, "monotonic", side_effect=[0, 10]
        ), patch.object(sleep_module, "sleep", side_effect=[True, False]) as wait:
            self.assertTrue(sleeper(0.125, stop_event=stop, check_interval=0.005))
            wait.assert_called_once_with(0.125, stop_event=stop, check_interval=0.005)
            self.assertFalse(sleeper(0.125))
        self.assertEqual(wait.call_args.args[0], 0.125)

    def test_already_stopped_call_does_not_wait(self):
        """An existing cancellation request returns without starting a schedule."""
        sleeper = simpytick.sleep_2()
        stop = threading.Event()
        stop.set()
        with patch.object(sleep_module, "sleep") as wait:
            self.assertTrue(sleeper(1, stop_event=stop))
        wait.assert_not_called()

    def test_invalid_arguments_do_not_advance_schedule(self):
        """Invalid durations or check intervals leave the next deadline unchanged."""
        sleeper = simpytick.sleep_2()
        with patch.object(
            sleep_module.time, "monotonic", side_effect=[0, 0.1875]
        ), patch.object(sleep_module, "sleep", return_value=False) as wait:
            sleeper(0.125)
            for seconds in (-1, float("nan"), float("inf")):
                with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                    sleeper(seconds)
            for interval in (0, -1, float("nan"), float("inf")):
                with self.subTest(interval=interval), self.assertRaises(ValueError):
                    sleeper(0.125, check_interval=interval)
            sleeper(0.125)
        self.assertEqual([entry.args[0] for entry in wait.call_args_list], [0.125, 0.0625])
