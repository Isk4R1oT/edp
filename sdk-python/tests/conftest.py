"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from edp.store import DecisionStore


@pytest.fixture
def tmp_store() -> Iterator[DecisionStore]:
    d = Path(tempfile.mkdtemp(prefix="edp_test_"))
    try:
        yield DecisionStore.open(d / ".edp")
    finally:
        shutil.rmtree(d, ignore_errors=True)
