"""T1 — django/django#11066 timezone migration. SWE-Bench-Verified hard.

Decisions forced early: migration strategy, backward-compat.
Expected horizon: 80-180 steps.
"""

from __future__ import annotations

from benchmark.tasks import TaskConfig
from benchmark.tasks.swebench._common import issue_prompt, make_check, make_setup

INSTANCE_ID = "django__django-11066"

ISSUE_TEXT = """\
RenameContentType._rename() doesn't save the content type on the correct
database. The migration mechanism uses the `using=db` parameter to specify
which database the operation should run on, but the call to `content_type.save()`
inside `RenameContentType._rename()` does not propagate the `using` argument.
This causes a migration failure when content types are renamed on a database
other than the default, because Django tries to update the row on the wrong
connection.

Reproduce:
  - Have a Django project with multiple databases configured
  - Run a migration that triggers RenameContentType on a non-default database
  - The migration fails because save() is called against the default database
"""

CONFIG = TaskConfig(
    id="django__django-11066",
    short_label="T1",
    source="swebench_verified",
    horizon_hint="80-180 steps",
    prompt=issue_prompt(INSTANCE_ID, ISSUE_TEXT),
    setup=make_setup(INSTANCE_ID),
    check=make_check(INSTANCE_ID),
)
