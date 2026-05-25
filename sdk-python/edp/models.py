"""Pydantic models for EDP Decision records.

Schema source: spec/v0.1/schema.json
Spec sections: §3.1 (required), §3.2 (optional), §3.3 (status workflow)
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Status = Literal[
    "proposed",
    "active",
    "superseded",
    "revised",
    "deprecated",
    "rejected",
]


class Alternative(BaseModel):
    label: str
    rejected_because: str


class ReviewEntry(BaseModel):
    ts: datetime
    step: int
    note: str
    ref: Optional[str] = None


class Decision(BaseModel):
    """A single EDP decision record. Immutable after write; changes go through supersede()."""

    # Required fields (§3.1)
    id: str = Field(pattern=r"^DEC-\d{4,}$")
    title: str = Field(max_length=120)
    status: Status
    created_at_step: int = Field(ge=0)
    created_at_ts: datetime
    created_by: str
    decision: str
    evidence: list[str] = Field(default_factory=list)

    # Optional fields (§3.2)
    tags: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    review_due_at_step: Optional[int] = Field(default=None, ge=0)
    key_constraints: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    revision_conditions: list[str] = Field(default_factory=list)
    context: Optional[str] = None
    alternatives: list[Alternative] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    review_history: list[ReviewEntry] = Field(default_factory=list)
    provisional: bool = False

    @field_validator("supersedes", "superseded_by")
    @classmethod
    def _validate_dec_ref(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.startswith("DEC-") or not v[4:].isdigit() or len(v[4:]) < 4:
            raise ValueError(f"invalid DEC reference: {v!r}")
        return v

    @field_validator("key_constraints")
    @classmethod
    def _validate_key_constraints(cls, v: list[str]) -> list[str]:
        for kc in v:
            if len(kc) > 140:
                raise ValueError(f"key_constraint exceeds 140 chars: {kc[:30]}...")
        return v

    @field_validator("invariants")
    @classmethod
    def _validate_invariants(cls, v: list[str]) -> list[str]:
        # invariants are machine-checkable predicates intended for the verifier;
        # 200-char budget gives room for predicate-shaped statements like
        # "all entries in competitor_list must have segment in ['enterprise']".
        # Per spec §3.6 each entry SHOULD be assertable — but the SDK does not
        # enforce this structurally (free text in v0.2; structured DSL is a v0.3
        # consideration).
        for inv in v:
            if len(inv) > 200:
                raise ValueError(f"invariant exceeds 200 chars: {inv[:30]}...")
        return v

    @field_validator("revision_conditions")
    @classmethod
    def _validate_revision_conditions(cls, v: list[str]) -> list[str]:
        for rc in v:
            if len(rc) > 200:
                raise ValueError(f"revision_condition exceeds 200 chars: {rc[:30]}...")
        return v

    def model_dump_storage(self) -> str:
        """Serialise to canonical JSON for storage."""
        return self.model_dump_json(exclude_none=False)


class RelevanceMatch(BaseModel):
    id: str
    relevance: float = Field(ge=0.0, le=1.0)
    why: str


class RelevanceReport(BaseModel):
    related: list[RelevanceMatch] = Field(default_factory=list)


Verdict = Literal["compatible", "violated", "uncertain"]


class CompatibilityReport(BaseModel):
    """Pre-action verifier verdict: does a planned action violate active invariants?

    Returned by `edp_verify(planned_action)` and by the optional PreToolUse
    verifier hook. Per spec §3.6 (v0.2):

      - `compatible`: no active invariant is violated by the planned action
      - `violated`: at least one invariant is violated; do not execute
      - `uncertain`: the verifier needs more evidence; escalate or supersede

    `violated_decision_ids` lists the decisions whose invariants the verifier
    found violated; populated only when verdict == "violated". `reasoning` is
    a short natural-language explanation suitable for surfacing to the agent
    so it can correct the planned action or call `edp_supersede` if the
    decision should change.
    """

    verdict: Verdict
    reasoning: str
    violated_decision_ids: list[str] = Field(default_factory=list)


class Event(BaseModel):
    """A single immutable event from the append-only log (§7.1)."""

    event_id: int
    ts: datetime
    actor: str
    decision_id: str
    op: Literal[
        "record",
        "supersede",
        "superseded_by",
        "revise",
        "deprecate",
        "reject",
        "review",
        "verify",
    ]
    payload: dict


def utcnow() -> datetime:
    """Return current UTC time with timezone — never use naive datetimes in EDP."""
    return datetime.now(timezone.utc)
