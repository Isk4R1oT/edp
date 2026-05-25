"""T4 — scikit-learn/scikit-learn#26323 cross-val refactor. SWE-Bench-Verified hard.

Decisions forced early: API shape.
Expected horizon: 80-180 steps.
"""

from __future__ import annotations

from benchmark.tasks import TaskConfig
from benchmark.tasks.swebench._common import issue_prompt, make_check, make_setup

INSTANCE_ID = "scikit-learn__scikit-learn-26323"

ISSUE_TEXT = """\
ColumnTransformer.set_output() ignores the `remainder` transformer. When a
user configures a ColumnTransformer with a remainder estimator (not the
default 'drop' or 'passthrough') and then calls .set_output(transform='pandas'),
the remainder transformer is NOT updated to also output a pandas DataFrame.
As a result, the final transformed output is a mix of pandas DataFrames
(from the named transformers) and the remainder's default output (often
a NumPy array), causing downstream pipeline failures.

Expected: set_output() should propagate to the remainder transformer too,
so the entire ColumnTransformer output is consistently pandas (or whatever
the requested format is).

Fix should be in ColumnTransformer.set_output() — iterate over all
fitted transformers including the remainder, not just the named ones.
"""

CONFIG = TaskConfig(
    id="scikit-learn__scikit-learn-26323",
    short_label="T4",
    source="swebench_verified",
    horizon_hint="80-180 steps",
    prompt=issue_prompt(INSTANCE_ID, ISSUE_TEXT),
    setup=make_setup(INSTANCE_ID),
    check=make_check(INSTANCE_ID),
)
