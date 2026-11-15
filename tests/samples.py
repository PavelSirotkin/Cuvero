"""The sample boards some tests compare against: the author's own boards, not published.

Tests that need them are skipped when the Samples folder is missing."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "Samples"
NO_SAMPLES = "no sample boards (folder Samples)"


def have_samples() -> bool:
    return (SAMPLES / "motor ir2101.lay6").exists()


def require_samples() -> None:
    """Skip the calling test module when the sample boards are missing."""
    if not have_samples():
        raise unittest.SkipTest(NO_SAMPLES)
