"""T2 — sympy/sympy#13865 matrix simplification. SWE-Bench-Verified hard.

Decisions forced early: algebraic-rewrite rule.
Expected horizon: 80-180 steps.
"""

from __future__ import annotations

from benchmark.tasks import TaskConfig
from benchmark.tasks.swebench._common import issue_prompt, make_check, make_setup

INSTANCE_ID = "sympy__sympy-13865"

ISSUE_TEXT = """\
ODE classification incorrectly recognizes Bernoulli ODE in some cases.
The function `classify_ode()` returns 'Bernoulli' for ODEs that have the
shape u' = a(x) * u + b(x) * u^n but where the coefficient detection
fails to handle terms collected against u^n properly. This causes the
solver to attempt a Bernoulli substitution that fails downstream.

Steps to reproduce:
  - Construct an ODE that visually looks Bernoulli-like but has its
    nonlinear-in-u coefficient encoded in a non-canonical form
  - Call classify_ode(eq, f(x))
  - Observe 'Bernoulli' is in the returned hints
  - Attempt dsolve(...) — it crashes or returns a wrong answer
"""

CONFIG = TaskConfig(
    id="sympy__sympy-13865",
    short_label="T2",
    source="swebench_verified",
    horizon_hint="80-180 steps",
    prompt=issue_prompt(INSTANCE_ID, ISSUE_TEXT),
    setup=make_setup(INSTANCE_ID),
    check=make_check(INSTANCE_ID),
)
