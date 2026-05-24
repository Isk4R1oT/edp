from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from edp.models import Decision


def _base_decision_kwargs(**overrides):
    base = dict(
        id="DEC-0001",
        title="Test decision",
        status="active",
        created_at_step=1,
        created_at_ts=datetime.now(timezone.utc),
        created_by="human:test",
        decision="Do the thing.",
        evidence=["@session_log/step_1/user"],
    )
    base.update(overrides)
    return base


def test_minimal_required_fields_ok():
    d = Decision(**_base_decision_kwargs())
    assert d.id == "DEC-0001"
    assert d.status == "active"
    assert d.confidence is None
    assert d.key_constraints == []


def test_invalid_id_format_rejected():
    with pytest.raises(ValidationError):
        Decision(**_base_decision_kwargs(id="0001"))
    with pytest.raises(ValidationError):
        Decision(**_base_decision_kwargs(id="DEC-1"))


def test_title_max_120():
    with pytest.raises(ValidationError):
        Decision(**_base_decision_kwargs(title="x" * 121))


def test_key_constraints_max_140():
    with pytest.raises(ValidationError):
        Decision(**_base_decision_kwargs(key_constraints=["x" * 141]))


def test_supersedes_ref_validation():
    with pytest.raises(ValidationError):
        Decision(**_base_decision_kwargs(supersedes="foo"))
    d = Decision(**_base_decision_kwargs(supersedes="DEC-0042"))
    assert d.supersedes == "DEC-0042"


def test_confidence_range():
    with pytest.raises(ValidationError):
        Decision(**_base_decision_kwargs(confidence=1.5))
    with pytest.raises(ValidationError):
        Decision(**_base_decision_kwargs(confidence=-0.1))
    d = Decision(**_base_decision_kwargs(confidence=0.5))
    assert d.confidence == 0.5
