"""T3 — astropy/astropy#14096 units serialization. SWE-Bench-Verified hard.

Decisions forced early: serialization format choice.
Expected horizon: 80-180 steps.
"""

from __future__ import annotations

from benchmark.tasks import TaskConfig
from benchmark.tasks.swebench._common import issue_prompt, make_check, make_setup

INSTANCE_ID = "astropy__astropy-14096"

ISSUE_TEXT = """\
Subclassed SkyCoord gives misleading attribute access message. When a user
subclasses SkyCoord and accesses an attribute that exists on the subclass
but raises (e.g. a property whose getter throws), the AttributeError message
incorrectly reports that the attribute does not exist on SkyCoord rather
than surfacing the underlying error.

Reproduction:
  - Create class MyCoord(SkyCoord) with a property `prop` whose getter
    raises e.g. KeyError
  - Instantiate MyCoord(...)
  - Access instance.prop
  - Observe AttributeError saying "no attribute 'prop'" rather than the
    real KeyError from the property's getter

The fix should make the underlying exception surface so the user can debug.
"""

CONFIG = TaskConfig(
    id="astropy__astropy-14096",
    short_label="T3",
    source="swebench_verified",
    horizon_hint="80-180 steps",
    prompt=issue_prompt(INSTANCE_ID, ISSUE_TEXT),
    setup=make_setup(INSTANCE_ID),
    check=make_check(INSTANCE_ID),
)
