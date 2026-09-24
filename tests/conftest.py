"""Make the repository root and the scripts/ package importable from any test directory."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def hermetically_restore_the_environment():
    """Several modules write os.environ directly (parameters.apply_params does).

    Snapshot and restore it around every test so one test's model/parameter
    choice can never leak into the next one.
    """
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)
