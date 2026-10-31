"""SimPyTick (Simple Python Tick)."""

import logging

from simpytick._version import __version__
from simpytick.sleep import sleep
from simpytick.sleep_2 import CompensatedSleep as sleep_2

__all__ = ["sleep", "sleep_2"]

logging.getLogger(__name__).addHandler(logging.NullHandler())
