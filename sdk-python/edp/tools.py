"""Core tool functions — the four agent-facing operations.

These are framework-agnostic Python callables. Bindings adapt them to specific
framework tool-registration conventions (see edp/bindings/).
"""

from __future__ import annotations

from typing import Optional

from edp.models import Decision, RelevanceReport
from edp.store import DecisionStore


def show(store: DecisionStore, decision_id: str) -> dict:
    """Return the full body of one decision (per spec §5.1)."""
    dec: Decision = store.show(decision_id)
    return dec.model_dump(mode="json")


def check(store: DecisionStore, planned_action: str) -> dict:
    """Return relevance report for a planned action (per spec §5.2).

    Agent-initiated soft check. Does not block or gate.
    """
    rep: RelevanceReport = store.check(planned_action)
    return rep.model_dump(mode="json")


def record(
    store: DecisionStore,
    *,
    title: str,
    decision: str,
    key_constraints: Optional[list[str]] = None,
    evidence: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    confidence: float = 0.7,
    actor: str = "agent",
    step: int = 0,
    review_due_at_step: Optional[int] = None,
    provisional: bool = False,
) -> str:
    """Create a new decision and return its id (per spec §5.3)."""
    return store.record(
        title=title,
        decision=decision,
        key_constraints=key_constraints or [],
        evidence=evidence or [],
        tags=tags or [],
        confidence=confidence,
        actor=actor,
        step=step,
        review_due_at_step=review_due_at_step,
        provisional=provisional,
    )


def supersede(
    store: DecisionStore,
    old_id: str,
    *,
    title: str,
    decision: str,
    key_constraints: Optional[list[str]] = None,
    evidence: Optional[list[str]] = None,
    confidence: float = 0.7,
    actor: str = "agent",
    step: int = 0,
    review_due_at_step: Optional[int] = None,
    provisional: bool = False,
) -> str:
    """Atomically supersede an existing decision (per spec §5.4)."""
    return store.supersede(
        old_id,
        title=title,
        decision=decision,
        key_constraints=key_constraints or [],
        evidence=evidence or [],
        confidence=confidence,
        actor=actor,
        step=step,
        review_due_at_step=review_due_at_step,
        provisional=provisional,
    )
