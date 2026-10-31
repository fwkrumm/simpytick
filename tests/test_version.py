"""Keep the importable version consistent with installed distribution metadata."""

import unittest
from importlib.metadata import version

from simpytick import __version__


class TestVersion(unittest.TestCase):
    """PDM metadata and package imports use the same release version."""

    def test_runtime_matches_distribution(self):
        """The installed distribution reports the same version as the package."""
        self.assertEqual(__version__, version("SimPyTick"))