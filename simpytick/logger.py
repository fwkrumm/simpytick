"""
Logging utilities: ``GrpcLogger`` adapter with project-specific levels and
a ``get_logger`` factory that attaches console + rotating file handlers.
"""
import logging
import tempfile
import warnings
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import coloredlogs

INTERNAL_DEBUG = 5
INTERNAL_INFO = 7


class GrpcLogger(logging.LoggerAdapter):
    """Adapt a standard logger with custom levels without changing its class."""

    def __init__(self, logger: logging.Logger | str):
        super().__init__(logging.getLogger(logger) if isinstance(logger, str) else logger, {})

    @property
    def handlers(self):
        """Return the underlying logger's handlers."""
        return self.logger.handlers

    @property
    def level(self) -> int:
        """Return the underlying logger's configured level."""
        return self.logger.level

    def iinfo(self, message, *args, **kwargs):
        """Log at INTERNAL_INFO level (7) --- framework lifecycle events, below DEBUG."""
        self.log(INTERNAL_INFO, message, *args, **kwargs)

    def idebug(self, message, *args, **kwargs):
        """
        Log at INTERNAL_DEBUG level (5) --- fine-grained framework tracing, below INTERNAL_INFO.
        """
        self.log(INTERNAL_DEBUG, message, *args, **kwargs)

    def setLevel(self, level) -> None:
        """Set level on the logger and all attached handlers simultaneously."""
        self.logger.setLevel(level)
        for handler in self.handlers:
            handler.setLevel(level)


_ADAPTERS: dict[str, GrpcLogger] = {}


def get_logger(
    name: str = "default",
    *,
    console_log_level: int | None = logging.INFO,
    log_dir: str = None,
    file_log_level: int | None = INTERNAL_DEBUG,
    use_colored_output: bool = True
) -> GrpcLogger:
    """
    Get or create a configured logger instance.

    Parameters
    ----------
    name : str
        Logger name (default: "default")
    console_log_level : int | None
        Console handler level. Set to None to disable console logging.
    log_dir : str
        Directory for log files. If None, uses system temp dir.
    file_log_level : int | None
        File handler level. Set to None to disable file logging.
    use_colored_output : bool
        Whether to use colored console output (default: True)

    Returns
    -------
    GrpcLogger
        Adapter around a configured standard logger. Importing this module does
        not register a global logger class or custom level names; level names
        are registered only when this factory is explicitly called.
    """
    logger = logging.getLogger(name)
    adapter = _ADAPTERS.setdefault(name, GrpcLogger(logger))
    logging.addLevelName(INTERNAL_DEBUG, "INTERNAL_DEBUG")
    logging.addLevelName(INTERNAL_INFO, "INTERNAL_INFO")

    # Avoid adding handlers multiple times
    if logger.handlers:
        warnings.warn(
            f"Logger '{name}' already configured; returning cached logger "\
                "and ignoring new settings.",
            stacklevel=2
        )
        return adapter

    # Logger level must be INTERNAL to allow file handler to capture everything
    # Individual handlers control their own output levels
    logger.setLevel(INTERNAL_DEBUG)
    logger.propagate = False

    # Determine log directory
    if log_dir is None:
        log_location = Path(tempfile.gettempdir()) / "grpcLogs"
    else:
        log_location = Path(log_dir)

    # Create file formatter
    file_formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler with coloredlogs
    if console_log_level is not None:
        if use_colored_output:
            # coloredlogs installs directly on the logger with field-level colors
            coloredlogs.install(
                level=console_log_level,
                logger=logger,
                fmt="%(asctime)s.%(msecs)03d %(hostname)s %(name)s[%(process)d] "\
                    "%(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                level_styles={
                    "internal_debug": {"color": "blue"},
                    "internal_info": {"color": "white"},
                    "debug": {"color": "cyan"},
                    "info": {"color": "green"},
                    "warning": {"color": "yellow", "bold": True},
                    "error": {"color": "red", "bold": True},
                    "critical": {"color": "red", "bold": True, "background": "white"}
                },
                field_styles={
                    "asctime": {"color": "white", "bold": True},
                    "hostname": {"color": "magenta"},
                    "levelname": {"color": "white", "bold": True},
                    "name": {"color": "cyan"},
                    "programname": {"color": "cyan"},
                    "process": {"color": "magenta"}
                }
            )
        else:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(console_log_level)
            console_handler.setFormatter(file_formatter)
            logger.addHandler(console_handler)

    # File handler with rotation
    if file_log_level is not None:
        try:
            log_location.mkdir(parents=True, exist_ok=True)

            # Generate timestamp for log filename
            timestamp = datetime.now().strftime("%Y%m%d")
            log_filename = log_location / f"{name}_{timestamp}.log"

            # Use TimedRotatingFileHandler for automatic daily rotation
            file_handler = TimedRotatingFileHandler(
                log_filename,
                when="midnight",
                interval=1,
                backupCount=30,  # Keep 30 days of logs
                encoding="utf-8"
            )
            file_handler.setLevel(file_log_level)
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            logger.info("Logging files to %s", log_location)

        except (PermissionError, OSError) as e:
            warnings.warn(
                f"Could not create log directory at {log_location}: {e}. "
                "File logging disabled.",
                stacklevel=2
            )

    return adapter
