"""Task registry — 10 locked tasks for the EDP benchmark.

Each task module exports a `CONFIG: TaskConfig` with:
  - id: stable task id (e.g. "T03" or "django__django-11066")
  - prompt: the initial user message string
  - setup(workspace): stages the workspace (clones repo, scaffolds files)
  - check(workspace): returns (task_success: bool, details: dict)

The TaskConfig protocol is duck-typed for simplicity. New tasks must NOT be
added after git tag `benchmark-prereg-v1` without opening a new pre-reg cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class TaskConfig:
    id: str
    short_label: str
    source: str  # "swebench_verified" or "custom"
    horizon_hint: str  # e.g. "80-180 steps"
    prompt: str
    setup: Callable[[Path], None]
    check: Callable[[Path], tuple[bool, dict]]


# Lazy imports avoid forcing every task's dependencies into the runner startup.
def _load_registry() -> dict[str, TaskConfig]:
    from benchmark.tasks.swebench import (
        t01_django_11066,
        t02_sympy_13865,
        t03_astropy_14096,
        t04_sklearn_26323,
        t05_sphinx_11445,
        t06_pytest_11604,
    )
    from benchmark.tasks.custom import (
        t07_tiny_tq_multisession,
        t08_hcast_ml_pipeline,
        t09_research_report,
        t10_project_plan_yougile,
    )

    configs: list[TaskConfig] = [
        t01_django_11066.CONFIG,
        t02_sympy_13865.CONFIG,
        t03_astropy_14096.CONFIG,
        t04_sklearn_26323.CONFIG,
        t05_sphinx_11445.CONFIG,
        t06_pytest_11604.CONFIG,
        t07_tiny_tq_multisession.CONFIG,
        t08_hcast_ml_pipeline.CONFIG,
        t09_research_report.CONFIG,
        t10_project_plan_yougile.CONFIG,
    ]
    return {c.id: c for c in configs}


TASK_REGISTRY: dict[str, TaskConfig] = _load_registry()
