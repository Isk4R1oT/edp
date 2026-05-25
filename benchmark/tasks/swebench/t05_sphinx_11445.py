"""T5 — sphinx-doc/sphinx#11445 extension lifecycle. SWE-Bench-Verified medium.

Decisions forced early: hook ordering.
Expected horizon: 60-140 steps.
"""

from __future__ import annotations

from benchmark.tasks import TaskConfig
from benchmark.tasks.swebench._common import issue_prompt, make_check, make_setup

INSTANCE_ID = "sphinx-doc__sphinx-11445"

ISSUE_TEXT = """\
Using rst_prolog removes the top heading when it contains a domain directive.
When the configuration option `rst_prolog` is set to a non-empty string and
a document's first heading uses a domain directive (for example, ":mod:" or
":py:func:"), the heading is silently stripped from the rendered output.

Reproduce:
  - Set rst_prolog = ".. include:: prolog.rst" in conf.py
  - Have a document whose first line is "==========\n:mod:`mypkg`\n=========="
  - Run sphinx-build
  - Observe the heading is missing from the rendered HTML / latex / man

The fix should preserve the heading regardless of whether rst_prolog is
in use, and regardless of whether the heading contains a domain directive.
Investigate the rst_prolog injection code path; the heading parser is
likely consuming or relocating the directive incorrectly.
"""

CONFIG = TaskConfig(
    id="sphinx-doc__sphinx-11445",
    short_label="T5",
    source="swebench_verified",
    horizon_hint="60-140 steps",
    prompt=issue_prompt(INSTANCE_ID, ISSUE_TEXT),
    setup=make_setup(INSTANCE_ID),
    check=make_check(INSTANCE_ID),
)
