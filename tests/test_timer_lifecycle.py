"""Timer context lifecycle tests with mocked workers and tick events."""

import logging
import unittest
from unittest.mock import Mock, patch

from simpytick._worker import run_worker
from simpytick.timer import TimedEvent, timer


class TestTimerLifecycle(unittest.TestCase):
    """Verify worker setup, cleanup, and iteration exits."""

    def test_invalid_backend_is_rejected(self):
        """Unknown backend names fail before any worker is constructed."""
        with self.assertRaisesRegex(ValueError, "Unsupported timer backend"):
            TimedEvent(s=0.01, n=1, backend="invalid")

    def test_process_backend_keeps_normal_priority_and_cleans_up(self):
        """Process setup forwards configuration without changing host priorities."""
        with patch("simpytick.timer._SPAWN_CONTEXT") as spawn, patch("psutil.Process") as process:
            reader, writer = Mock(), Mock()
            reader.poll.return_value = False
            spawn.Pipe.return_value = (reader, writer)
            logger = Mock(level=logging.WARNING)
            logger.getEffectiveLevel.return_value = logging.WARNING
            context = TimedEvent(s=0.02, n=3, compensation=False, logger=logger)
            with context as entered:
                self.assertIs(entered, context)
                spawn.Process.assert_called_once_with(
                    target=run_worker,
                    args=(timer, (3, 0.02, spawn.Event.return_value), {
                        "enable_compensation": False,
                        "logger_level": logging.WARNING,
                        "stop_event": None,
                    }, writer), daemon=True,
                )
                spawn.Process.return_value.start.assert_called_once_with()
                process.assert_not_called()
            spawn.Process.return_value.terminate.assert_called_once_with()
            spawn.Process.return_value.join.assert_called_once_with()
            reader.close.assert_called_once_with()
            writer.close.assert_called()

    def test_standard_logger_adapter_can_configure_worker(self):
        """Standard adapters need no custom level property to configure a timer."""
        logger = logging.LoggerAdapter(logging.Logger("application", logging.WARNING), {})
        with patch("simpytick.timer.threading.Thread") as worker:
            with TimedEvent(s=0.01, n=1, logger=logger, backend="thread"):
                kwargs = worker.call_args.kwargs["args"][2]
                self.assertEqual(kwargs["logger_level"], logging.WARNING)

    def test_partial_start_failure_reaps_worker_and_closes_status(self):
        """A startup exception cannot leave a started process running."""
        with patch("simpytick.timer._SPAWN_CONTEXT") as spawn:
            reader, writer = Mock(), Mock()
            spawn.Pipe.return_value = (reader, writer)
            worker = spawn.Process.return_value
            worker.start.side_effect = OSError("startup failed")
            context = TimedEvent(s=0.01, n=-1)
            with self.assertRaisesRegex(OSError, "startup failed"):
                context.__enter__()
            worker.terminate.assert_called_once_with()
            worker.join.assert_called_once_with()
            reader.close.assert_called()
            writer.close.assert_called()

    def test_failed_start_without_process_closes_status(self):
        """Failure before process creation closes handles without joining an unstarted worker."""
        with patch("simpytick.timer._SPAWN_CONTEXT") as spawn:
            reader, writer = Mock(), Mock()
            spawn.Pipe.return_value = (reader, writer)
            worker = spawn.Process.return_value
            worker.pid = None
            worker.start.side_effect = OSError("not started")
            context = TimedEvent(s=0.01, n=-1)
            with self.assertRaisesRegex(OSError, "not started"):
                context.__enter__()
            worker.join.assert_not_called()
            reader.close.assert_called_once_with()
            writer.close.assert_called_once_with()

    def test_thread_cleanup_signals_stop_joins_and_preserves_error(self):
        """Application failure still requests thread shutdown and is never suppressed."""
        context = TimedEvent(s=0.01, n=-1, backend="thread")
        with patch("simpytick.timer.threading.Thread") as worker:
            with self.assertRaisesRegex(RuntimeError, "task failed"):
                with context:
                    raise RuntimeError("task failed")
        self.assertTrue(context._stop_event.is_set())  # pylint: disable=protected-access
        worker.return_value.join.assert_called_once_with()
        worker.return_value.terminate.assert_not_called()

    def test_exit_without_worker_does_not_suppress_exception(self):
        """Cleanup is safe even when context entry never created a worker."""
        context = TimedEvent(s=0.01, n=1, backend="thread")
        self.assertFalse(context.__exit__(None, None, None))

    def test_dead_worker_reports_missed_ticks(self):
        """A finished worker with missing ticks ends iteration rather than deadlocking."""
        logger = Mock()
        context = TimedEvent(s=0.02, n=3, logger=logger, backend="thread")
        setattr(context, "_worker_result", ("done", None))
        with patch.object(context, "_event") as event, patch.object(context, "_worker") as worker:
            event.wait.side_effect = [True, False, False]
            event.is_set.return_value = False
            worker.is_alive.side_effect = [True, False]
            self.assertEqual(list(context), [0])
        event.wait.assert_called_with(timeout=0.02)
        event.clear.assert_called_once_with()
        logger.warning.assert_called_once_with(
            "Timer process ended after %d ticks; %d tick(s) missed.", 1, 2
        )

    def test_unexpected_worker_exit_raises_without_logger(self):
        """A dead worker without a completion message is never silent."""
        context = TimedEvent(s=60, n=-1, backend="thread")
        with patch.object(context, "_event") as event, patch.object(context, "_worker") as worker:
            event.wait.side_effect = [True, True, False]
            worker.is_alive.return_value = False
            with self.assertRaisesRegex(RuntimeError, "without completion"):
                list(context)
        event.wait.assert_called_with(timeout=0.1)

    def test_thread_failure_is_propagated_without_logger(self):
        """Background exceptions reach the consumer even with a long interval."""
        with patch("simpytick.timer.timer", side_effect=ValueError("worker failed")):
            with self.assertRaisesRegex(RuntimeError, "ValueError: worker failed"):
                with TimedEvent(s=60, n=-1, backend="thread") as context:
                    list(context)
        self.assertFalse(getattr(context, "_worker").is_alive())

    def test_reported_error_is_not_hidden_by_application_error(self):
        """An application exception remains primary during worker cleanup."""
        with self.assertRaisesRegex(LookupError, "application failed"):
            with TimedEvent(s=60, n=-1, backend="thread") as context:
                setattr(context, "_worker_result", ("error", "worker failed"))
                raise LookupError("application failed")

    def test_zero_cycles_yield_no_ticks(self):
        """An empty timer returns an empty iterator."""
        with TimedEvent(s=0.01, n=0, backend="thread") as context:
            self.assertEqual(list(context), [])

    def test_interrupt_is_logged_and_reraised(self):
        """Iteration never swallows Ctrl+C, with or without an application logger."""
        for logger in (None, Mock()):
            with self.subTest(logger=logger):
                context = TimedEvent(s=0.01, n=1, logger=logger, backend="thread")
                with patch.object(context, "_event") as event:
                    event.wait.side_effect = KeyboardInterrupt
                    with self.assertRaises(KeyboardInterrupt):
                        next(iter(context))
                if logger is not None:
                    logger.info.assert_called_once_with("strg+c")
