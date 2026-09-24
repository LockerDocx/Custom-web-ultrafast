"""Make the repository root and the scripts/ package importable from any test directory."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_runtime_evidence(tmp_path, monkeypatch):
    """Keep per-model runtime evidence out of the repo and out of other tests."""
    from jev_ultrafast import schemas

    monkeypatch.setattr(schemas, "RUNTIME_PATH", tmp_path / "model-runtime.json")
    yield
