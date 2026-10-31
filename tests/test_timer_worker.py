"""Deterministic timer worker tests without sleeps or child processes."""

import itertools
import logging
import threading
import unittest
from unittest.mock import Mock, call, patch

from simpytick._worker import run_worker
from simpytick.timer import _cycles, _wait_for_next_tick, timer


class TestWorkerStatus(unittest.TestCase):
    """Report a single terminal status and always release the writer."""

    def test_success_reports_completion(self):
        """Successful worker calls retain their arguments and report normal completion."""
        target, status = Mock(), Mock()
        run_worker(target, (1,), {"option": True}, status)
        target.assert_called_once_with(1, option=True)
        status.send.assert_called_once_with(("done", None))
        status.close.assert_called_once_with()

    def test_base_exceptions_are_reported_with_bounded_messages(self):
        """SystemExit and ordinary failures cannot masquerade as normal completion."""
        for error in (ValueError("failure"), SystemExit(2), ValueError("x" * 10000)):
            with self.subTest(error=type(error).__name__):
                status = Mock()
                run_worker(Mock(side_effect=error), (), {}, status)
                kind, message = status.send.call_args.args[0]
                self.assertEqual(kind, "error")
                self.assertTrue(message.startswith(f"{type(error).__name__}: "))
                self.assertLessEqual(len(message), len(type(error).__name__) + 1002)
                status.close.assert_called_once_with()


class TestTimerWorker(unittest.TestCase):
    """Verify interval calculation, drift correction, overruns, and early stops."""

    def test_cycle_sequences_include_infinite_mode(self):
        """Finite counts stop exactly; infinite mode yields consecutive indices."""
        self.assertEqual(list(_cycles(0)), [])
        self.assertEqual(list(_cycles(3)), [0, 1, 2])
        self.assertEqual(list(itertools.islice(_cycles(-1), 4)), [0, 1, 2, 3])

    def test_interval_wait_uses_sleep_without_stop_event(self):
        """Process waits sleep for the requested duration."""
        with patch("simpytick.timer.time.sleep") as sleep:
            self.assertFalse(_wait_for_next_tick(0.25))
        sleep.assert_called_once_with(0.25)

    def test_interval_wait_stops_between_sleep_chunks(self):
        """A stop request after a sleep prevents the next chunk."""
        stop = threading.Event()
        with patch("simpytick.timer.time.monotonic", return_value=0.0), patch(
            "simpytick.timer.time.sleep", side_effect=lambda duration: stop.set()
        ) as sleep:
            self.assertTrue(_wait_for_next_tick(60.0, stop))
        sleep.assert_called_once_with(0.01)

    def test_interval_wait_uses_remaining_deadline(self):
        """Sleep overhead reduces the final chunk rather than extending the wait."""
        stop = threading.Event()
        with patch(
            "simpytick.timer.time.monotonic", side_effect=[0.0, 0.0, 0.02, 0.025]
        ), patch("simpytick.timer.time.sleep") as sleep:
            self.assertFalse(_wait_for_next_tick(0.025, stop))
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(sleep.call_args_list[0], call(0.01))
        self.assertAlmostEqual(sleep.call_args_list[1].args[0], 0.005)

    def test_interval_wait_handles_preexisting_stop_and_zero_duration(self):
        """Stopped and expired waits do not sleep."""
        stop = threading.Event()
        with patch("simpytick.timer.time.monotonic", return_value=0.0), patch(
            "simpytick.timer.time.sleep"
        ) as sleep:
            self.assertFalse(_wait_for_next_tick(0.0, stop))
            stop.set()
            self.assertTrue(_wait_for_next_tick(60.0, stop))
        sleep.assert_not_called()

    def test_compensation_adjusts_next_interval_and_reports_overrun(self):
        """Elapsed overhead shortens the next wait and overruns retain logging."""
        event = Mock()
        event.is_set.return_value = True
        with patch("simpytick.timer.get_logger") as logger, patch(
            "simpytick.timer.time.monotonic", side_effect=[0.0, 0.0, 0.1875]
        ), patch(
            "simpytick.timer._wait_for_next_tick", return_value=False
        ) as wait:
            timer(2, 0.125, event, logger_level=logging.WARNING)
        logger.assert_called_once_with(
            "timer", console_log_level=logging.WARNING, file_log_level=None
        )
        self.assertEqual(wait.call_args_list, [call(0.125, None), call(0.0625, None)])
        self.assertEqual(event.set.call_count, 2)
        self.assertEqual(logger.return_value.warning.call_count, 2)
        self.assertEqual(logger.return_value.warning.call_args.args[1], 2)

    def test_compensation_catches_up_without_reading_wall_clock(self):
        """Missed deadlines yield zero waits until the monotonic schedule recovers."""
        event = Mock()
        event.is_set.return_value = False
        with patch(
            "simpytick.timer.time.monotonic",
            side_effect=[0.0, 0.0, 0.1875, 0.5, 0.5, 0.5],
        ), patch("simpytick.timer.time.time", side_effect=AssertionError), patch(
            "simpytick.timer.time.time_ns", side_effect=AssertionError
        ), patch("simpytick.timer._wait_for_next_tick", return_value=False) as wait:
            timer(5, 0.125, event)
        self.assertEqual(
            wait.call_args_list,
            [call(0.125, None), call(0.0625, None), call(0.0, None),
             call(0.0, None), call(0.125, None)],
        )
        self.assertEqual(event.set.call_count, 5)

    def test_uncompensated_ticks_use_fixed_waits_and_fire_immediately(self):
        """Fixed waits need no clock and always follow their event signal."""
        event = Mock()
        operations = []
        event.set.side_effect = lambda: operations.append("tick")
        event.is_set.return_value = False
        with patch("simpytick.timer.time.monotonic", side_effect=AssertionError), patch(
            "simpytick.timer._wait_for_next_tick",
            side_effect=lambda duration, stop: operations.append(duration),
        ):
            timer(2, 0.125, event, False)
        self.assertEqual(operations, ["tick", 0.125, "tick", 0.125])

    def test_compensation_has_no_decimal_precision_restriction(self):
        """Deadline scheduling accepts periods unsupported by the old digit heuristic."""
        event = Mock()
        event.is_set.return_value = False
        with patch("simpytick.timer.time.monotonic", return_value=0.0), patch(
            "simpytick.timer._wait_for_next_tick", return_value=False
        ) as wait:
            timer(1, 0.0001, event)
        wait.assert_called_once_with(0.0001, None)
        event.reset_mock()
        timer(0, 1e20, event)
        event.set.assert_not_called()

    def test_shutdown_before_tick_and_during_wait(self):
        """Thread shutdown prevents new ticks or interrupts the current wait."""
        stop = threading.Event()
        stop.set()
        event = Mock()
        timer(-1, 0.01, event, False, stop_event=stop)
        event.set.assert_not_called()
        stop.clear()
        with patch(
            "simpytick.timer._wait_for_next_tick", return_value=True
        ) as wait:
            timer(-1, 0.01, event, False, stop_event=stop)
        event.set.assert_called_once_with()
        wait.assert_called_once_with(0.01, stop)
