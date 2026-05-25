"""T6 — pytest-dev/pytest#11604 collection plugin. SWE-Bench-Verified medium.

Decisions forced early: plugin vs monkey-patch.
Expected horizon: 60-140 steps.
"""

from __future__ import annotations

from benchmark.tasks import TaskConfig
from benchmark.tasks.swebench._common import issue_prompt, make_check, make_setup

INSTANCE_ID = "pytest-dev__pytest-11604"

ISSUE_TEXT = """\
Pytest collection: when a conftest.py is moved up the directory tree such
that the relative test path crosses a missing __init__.py boundary, pytest
fails to import the test module with a confusing 'package not found' error
rather than skipping or reporting a clearer message.

Reproduce:
  - Create tests/ with no __init__.py
  - Create tests/subdir/test_foo.py with a simple test
  - Move conftest.py from tests/subdir/ to tests/
  - Run pytest tests/
  - Observe a misleading error about package resolution

The fix should detect the missing __init__.py condition and emit a clear
error message ("missing __init__.py at <path> blocks importing
<test_module>; either add __init__.py or restructure"), or handle the
import gracefully.
"""

CONFIG = TaskConfig(
    id="pytest-dev__pytest-11604",
    short_label="T6",
    source="swebench_verified",
    horizon_hint="60-140 steps",
    prompt=issue_prompt(INSTANCE_ID, ISSUE_TEXT),
    setup=make_setup(INSTANCE_ID),
    check=make_check(INSTANCE_ID),
)
