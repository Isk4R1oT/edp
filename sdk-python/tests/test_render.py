from datetime import datetime, timezone

from edp.models import Alternative, Decision
from edp.render import render_full_markdown, render_snippet, wrap_active_block


def _dec(**overrides):
    base = dict(
        id="DEC-0042",
        title="Focus on enterprise B2B",
        status="active",
        created_at_step=12,
        created_at_ts=datetime.now(timezone.utc),
        created_by="human:igor",
        decision="Restrict scope to enterprise.",
        evidence=["@session_log/step_8/user_message"],
        key_constraints=["enterprise only", "ACV>=$50k"],
        confidence=0.85,
        review_due_at_step=100,
    )
    base.update(overrides)
    return Decision(**base)


def test_snippet_format():
    snip = render_snippet(_dec())
    lines = snip.split("\n")
    assert len(lines) <= 4
    assert lines[0].startswith("DEC-0042 [active]")
    assert "conf=0.85" in lines[0]
    assert "due=step:100" in lines[0]
    assert "Title:" in lines[1]
    assert "Key constraints:" in lines[2]


def test_snippet_supersede_marker():
    d = _dec(status="superseded", superseded_by="DEC-0051")
    snip = render_snippet(d)
    assert "→ see DEC-0051" in snip


def test_snippet_provisional_marker():
    d = _dec(provisional=True)
    snip = render_snippet(d)
    assert "provisional" in snip


def test_snippet_triggers_marker_when_revision_conditions_present():
    d = _dec(revision_conditions=["trigger-A", "trigger-B"])
    snip = render_snippet(d)
    assert "triggers:2" in snip


def test_snippet_no_triggers_marker_when_empty():
    d = _dec(revision_conditions=[])
    snip = render_snippet(d)
    assert "triggers:" not in snip


def test_full_markdown_includes_revision_conditions_section():
    d = _dec(revision_conditions=["pgvector p95 > 50ms", "ANN recall < 0.9"])
    md = render_full_markdown(d)
    assert "## Revision conditions" in md
    assert "pgvector p95 > 50ms" in md
    assert "ANN recall < 0.9" in md


def test_wrap_active_block_includes_precedence():
    text = wrap_active_block(["DEC-0001 [active]\n  Title: x"], version=3, total_active=1)
    assert '<edp:active version="3">' in text
    assert "Active: 1" in text
    assert 'use only version="3"' in text


def test_full_markdown_has_frontmatter():
    d = _dec(
        context="Some context here.",
        alternatives=[Alternative(label="Hybrid", rejected_because="doubles scope")],
        consequences=["Smaller scope"],
    )
    md = render_full_markdown(d)
    assert md.startswith("---\n")
    assert "id: DEC-0042" in md
    assert "## Context" in md
    assert "## Decision" in md
    assert "## Alternatives considered" in md
    assert "REJECTED: doubles scope" in md
    assert "## Consequences" in md
