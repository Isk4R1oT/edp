"""Tests for the constraints primitive (v0.3, spec §3.8).

Covers:
  - Model validation (id pattern, rule length)
  - Store CRUD: add, list, show, remove, confirm
  - Append-only event log records con_add / con_remove / con_confirm
  - Markdown projection writes to .edp/constraints/CON-NNNN.md
  - No supersede chain (constraints have no `superseded_by`)
  - Active block: constraints rendered at top, never trimmed
  - MCP server: read tool always present; write tool mode-gated
  - Verifier: constraints included in user message
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from edp.cli import app
from edp.models import Constraint
from edp.render import (
    render_constraint_markdown,
    render_constraint_snippet,
    wrap_active_block,
)
from edp.selector import SelectorPolicy, get_active_block
from edp.store import DecisionNotFound


runner = CliRunner()


# ── Model ─────────────────────────────────────────────────────────────────────


def test_constraint_id_pattern():
    with pytest.raises(ValidationError):
        Constraint(
            id="DEC-0001",  # wrong prefix
            rule="x",
            created_at_ts=datetime.now(timezone.utc),
            created_by="t",
        )


def test_constraint_rule_max_length():
    with pytest.raises(ValidationError):
        Constraint(
            id="CON-0001",
            rule="x" * 201,
            created_at_ts=datetime.now(timezone.utc),
            created_by="t",
        )


def test_constraint_minimal_shape():
    """A constraint requires only id, rule, ts, author — nothing else."""
    c = Constraint(
        id="CON-0001",
        rule="Max leverage 10x",
        created_at_ts=datetime.now(timezone.utc),
        created_by="human:cli",
    )
    assert c.tags == []
    assert c.provisional is False
    # No status / confidence / supersede fields — by design.
    assert not hasattr(c, "status")
    assert not hasattr(c, "supersedes")
    assert not hasattr(c, "confidence")


# ── Store CRUD ────────────────────────────────────────────────────────────────


def test_add_constraint_returns_sequential_ids(tmp_store):
    a = tmp_store.add_constraint(rule="Max leverage 10x", tags=["risk"])
    b = tmp_store.add_constraint(rule="Every order has stop-loss")
    assert a == "CON-0001"
    assert b == "CON-0002"


def test_list_constraints_ordered_by_id(tmp_store):
    tmp_store.add_constraint(rule="A")
    tmp_store.add_constraint(rule="B")
    tmp_store.add_constraint(rule="C")
    rows = tmp_store.list_constraints()
    assert [c.id for c in rows] == ["CON-0001", "CON-0002", "CON-0003"]


def test_show_constraint_roundtrip(tmp_store):
    cid = tmp_store.add_constraint(
        rule="No trading 30min after FOMC",
        tags=["risk", "news"],
    )
    c = tmp_store.show_constraint(cid)
    assert c.rule == "No trading 30min after FOMC"
    assert c.tags == ["risk", "news"]
    assert c.provisional is False


def test_show_constraint_missing_raises(tmp_store):
    with pytest.raises(DecisionNotFound):
        tmp_store.show_constraint("CON-9999")


def test_remove_constraint_drops_from_current_but_event_persists(tmp_store):
    cid = tmp_store.add_constraint(rule="x")
    tmp_store.remove_constraint(cid, reason="policy change")
    with pytest.raises(DecisionNotFound):
        tmp_store.show_constraint(cid)
    # Event log keeps the history
    events = tmp_store.events(decision_id=cid)
    ops = [e.op for e in events]
    assert "con_add" in ops
    assert "con_remove" in ops
    # Reason captured in payload
    removed = [e for e in events if e.op == "con_remove"][0]
    assert removed.payload.get("_remove_reason") == "policy change"


def test_confirm_constraint_promotes_provisional(tmp_store):
    cid = tmp_store.add_constraint(rule="x", provisional=True, actor="agent")
    assert tmp_store.show_constraint(cid).provisional is True
    tmp_store.confirm_constraint(cid)
    assert tmp_store.show_constraint(cid).provisional is False
    ops = [e.op for e in tmp_store.events(decision_id=cid)]
    assert "con_confirm" in ops


def test_confirm_constraint_idempotent_on_confirmed(tmp_store):
    cid = tmp_store.add_constraint(rule="x", provisional=False)
    # Should not raise or emit an extra event
    tmp_store.confirm_constraint(cid)
    ops = [e.op for e in tmp_store.events(decision_id=cid)]
    assert ops.count("con_confirm") == 0


# ── Markdown projection ───────────────────────────────────────────────────────


def test_constraint_markdown_written_to_disk(tmp_store):
    cid = tmp_store.add_constraint(rule="Max leverage 10x", tags=["risk"])
    md_path = tmp_store.constraints_dir / f"{cid}.md"
    assert md_path.is_file()
    text = md_path.read_text()
    assert "Max leverage 10x" in text
    assert "risk" in text


def test_constraint_markdown_removed_on_delete(tmp_store):
    cid = tmp_store.add_constraint(rule="x")
    md_path = tmp_store.constraints_dir / f"{cid}.md"
    assert md_path.is_file()
    tmp_store.remove_constraint(cid)
    assert not md_path.exists()


def test_render_constraint_markdown_shape():
    c = Constraint(
        id="CON-0001",
        rule="Max leverage 10x",
        created_at_ts=datetime(2026, 5, 26, tzinfo=timezone.utc),
        created_by="human:cli",
        tags=["risk"],
    )
    md = render_constraint_markdown(c)
    assert "id: CON-0001" in md
    assert "## Rule" in md
    assert "Max leverage 10x" in md
    # No status / supersede / confidence shape leakage.
    assert "status:" not in md
    assert "supersedes:" not in md
    assert "confidence:" not in md


# ── Snippet + active block ────────────────────────────────────────────────────


def test_constraint_snippet_compact_format():
    c = Constraint(
        id="CON-0001",
        rule="Max leverage 10x",
        created_at_ts=datetime.now(timezone.utc),
        created_by="t",
        tags=["risk"],
    )
    snip = render_constraint_snippet(c)
    assert "CON-0001" in snip
    assert "Max leverage 10x" in snip
    assert "risk" in snip


def test_constraint_snippet_marks_provisional():
    c = Constraint(
        id="CON-0001",
        rule="x",
        created_at_ts=datetime.now(timezone.utc),
        created_by="agent",
        provisional=True,
    )
    snip = render_constraint_snippet(c)
    assert "[provisional]" in snip


def test_active_block_renders_constraints_section(tmp_store):
    tmp_store.add_constraint(rule="Max leverage 10x", tags=["risk"])
    tmp_store.record(title="t", decision="d", evidence=[])
    result = get_active_block(tmp_store)
    text = result.text
    assert "Constraints (non-negotiable axioms" in text
    assert "Max leverage 10x" in text
    assert "Decisions (revisable" in text
    # Order: constraints section before decisions section
    assert text.index("Max leverage 10x") < text.index("Decisions (revisable")


def test_active_block_constraints_never_trimmed(tmp_store):
    # Add many constraints + tiny budget. Constraints must still all appear.
    for i in range(8):
        tmp_store.add_constraint(rule=f"Constraint number {i}", tags=["risk"])
    # Tiny budget — would aggressively trim decisions, but constraints stay.
    result = get_active_block(tmp_store, policy=SelectorPolicy(token_budget=50))
    for i in range(8):
        assert f"Constraint number {i}" in result.text


def test_active_block_no_constraints_section_when_empty(tmp_store):
    tmp_store.record(title="t", decision="d", evidence=[])
    text = get_active_block(tmp_store).text
    assert "Constraints (non-negotiable axioms" not in text


def test_active_block_footer_reflects_constraint_count(tmp_store):
    tmp_store.add_constraint(rule="x")
    tmp_store.add_constraint(rule="y")
    tmp_store.record(title="t", decision="d", evidence=[])
    text = get_active_block(tmp_store).text
    assert "Constraints: 2" in text


def test_active_block_tag_filter_includes_untagged_constraints(tmp_store):
    """An untagged constraint should always render; tagged ones gate on context."""
    tmp_store.add_constraint(rule="Untagged axiom")
    tmp_store.add_constraint(rule="Risk-tagged axiom", tags=["risk"])
    tmp_store.add_constraint(rule="Compliance-tagged axiom", tags=["compliance"])
    result = get_active_block(tmp_store, context_tags=["risk"])
    text = result.text
    assert "Untagged axiom" in text
    assert "Risk-tagged axiom" in text
    assert "Compliance-tagged axiom" not in text


# ── No-supersede semantics ────────────────────────────────────────────────────


def test_constraints_have_no_supersede_method(tmp_store):
    """Store offers add/remove/confirm — but not supersede — for constraints."""
    assert hasattr(tmp_store, "add_constraint")
    assert hasattr(tmp_store, "remove_constraint")
    assert hasattr(tmp_store, "confirm_constraint")
    assert not hasattr(tmp_store, "supersede_constraint")


# ── Wrap_active_block direct API ──────────────────────────────────────────────


def test_wrap_active_block_with_constraints_parameter():
    text = wrap_active_block(
        ["DEC-0001 [active]\n  Title: x"],
        version=1,
        total_active=1,
        constraint_snippets=["  CON-0001: Max leverage 10x"],
        total_constraints=1,
    )
    assert "Constraints (non-negotiable axioms" in text
    assert "Max leverage 10x" in text
    assert "Constraints: 1" in text
    assert "Active decisions: 1" in text


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_cli_constraint_add_then_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EDP_STORE", str(tmp_path / ".edp"))
    r = runner.invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["constraint", "add", "--rule", "Max leverage 10x", "--tag", "risk"])
    assert r.exit_code == 0, r.output
    assert "CON-0001" in r.output
    r = runner.invoke(app, ["constraint", "list"])
    assert r.exit_code == 0
    assert "CON-0001" in r.output
    assert "Max leverage 10x" in r.output


def test_cli_constraint_remove(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EDP_STORE", str(tmp_path / ".edp"))
    runner.invoke(app, ["init"])
    runner.invoke(app, ["constraint", "add", "--rule", "x"])
    r = runner.invoke(app, ["constraint", "remove", "CON-0001", "--reason", "policy"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["constraint", "list"])
    assert "(no constraints)" in r.output


def test_cli_constraint_confirm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EDP_STORE", str(tmp_path / ".edp"))
    runner.invoke(app, ["init"])
    runner.invoke(app, ["constraint", "add", "--rule", "x", "--provisional"])
    r = runner.invoke(app, ["constraint", "show", "CON-0001", "--json"])
    body = json.loads(r.output)
    assert body["provisional"] is True
    r = runner.invoke(app, ["constraint", "confirm", "CON-0001"])
    assert r.exit_code == 0
    r = runner.invoke(app, ["constraint", "show", "CON-0001", "--json"])
    body = json.loads(r.output)
    assert body["provisional"] is False


# ── MCP server: mode-gated write tool ─────────────────────────────────────────


async def _tool_names(server) -> set[str]:
    tools = await server.list_tools()
    return {t.name for t in tools}


async def test_mcp_server_default_hides_add_constraint(tmp_path, monkeypatch):
    """Default mode (human_only) does NOT expose edp_add_constraint."""
    monkeypatch.delenv("EDP_CONSTRAINT_MODE", raising=False)
    from edp.server import create_server

    server = create_server(str(tmp_path / ".edp"))
    names = await _tool_names(server)
    assert "edp_constraints" in names  # read always present
    assert "edp_add_constraint" not in names


async def test_mcp_server_agent_auto_exposes_add_constraint(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_CONSTRAINT_MODE", "agent_auto")
    from edp.server import create_server

    server = create_server(str(tmp_path / ".edp"))
    names = await _tool_names(server)
    assert "edp_constraints" in names
    assert "edp_add_constraint" in names


async def test_mcp_server_agent_provisional_exposes_add_constraint(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_CONSTRAINT_MODE", "agent_provisional")
    from edp.server import create_server

    server = create_server(str(tmp_path / ".edp"))
    names = await _tool_names(server)
    assert "edp_add_constraint" in names


# ── Verifier prompt includes constraints ──────────────────────────────────────


def test_verifier_user_message_includes_constraints():
    from edp.verifier import _build_user_message

    c = Constraint(
        id="CON-0001",
        rule="Max leverage 10x",
        created_at_ts=datetime.now(timezone.utc),
        created_by="t",
    )
    msg = _build_user_message("place 50x leveraged order", [], active_constraints=[c])
    assert "ACTIVE CONSTRAINTS" in msg
    assert "Max leverage 10x" in msg
    assert "CON-0001" in msg


def test_verifier_user_message_no_constraints_section_when_empty():
    from edp.verifier import _build_user_message

    msg = _build_user_message("do thing", [], active_constraints=[])
    # Header still rendered with empty marker (so the model knows none exist)
    assert "ACTIVE CONSTRAINTS" in msg
    assert "(no active constraints)" in msg
