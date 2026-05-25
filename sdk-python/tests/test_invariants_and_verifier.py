"""Tests for v0.2.0 additions — invariants field + verifier path.

Covers:
  - invariants field is persisted and round-trips through store
  - render_snippet surfaces inv:N marker when invariants present
  - render_full_markdown emits an ## Invariants section
  - PROTOCOL_PRIMER mentions edp_verify and inv:N marker
  - wrap_active_block footer mentions edp.verify(action)
  - verifier_hook fail-open behaviour when anthropic SDK is missing
  - verifier_hook silent passthrough when EDP_STORE missing
  - claude-code install --enable-verifier writes PreToolUse hook
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from edp.cli import app
from edp.models import CompatibilityReport
from edp.render import (
    PROTOCOL_PRIMER,
    render_full_markdown,
    render_snippet,
    wrap_active_block,
)


runner = CliRunner()


# ── invariants field ────────────────────────────────────────────────────────

def test_invariants_roundtrip_through_store(tmp_store):
    dec_id = tmp_store.record(
        title="JSON-only endpoints",
        decision="All new endpoints expose only JSON.",
        key_constraints=["no XML serialisation"],
        invariants=[
            "all new endpoints MUST return application/json",
            "response_class MUST NOT be XMLResponse",
        ],
        evidence=["src/api/endpoints.py"],
        confidence=0.9,
    )
    loaded = tmp_store.show(dec_id)
    assert loaded.invariants == [
        "all new endpoints MUST return application/json",
        "response_class MUST NOT be XMLResponse",
    ]


def test_invariants_default_empty_for_back_compat(tmp_store):
    """Records without invariants land at []; old v0.1 callers keep working."""
    dec_id = tmp_store.record(
        title="legacy decision",
        decision="without invariants",
        key_constraints=[],
        evidence=[],
    )
    loaded = tmp_store.show(dec_id)
    assert loaded.invariants == []


def test_invariants_length_validation():
    """200-char budget per invariant; longer entries reject."""
    from edp.models import Decision, utcnow

    long_inv = "x" * 250
    with pytest.raises(ValueError, match="invariant exceeds 200 chars"):
        Decision(
            id="DEC-0001",
            title="t",
            status="active",
            created_at_step=0,
            created_at_ts=utcnow(),
            created_by="test",
            decision="d",
            invariants=[long_inv],
        )


def test_invariants_supersede_chain_carries_invariants(tmp_store):
    a = tmp_store.record(
        title="orig",
        decision="d",
        invariants=["INV-orig: must hold"],
        evidence=[],
    )
    b = tmp_store.supersede(
        a,
        title="updated",
        decision="d2",
        invariants=["INV-new: must hold differently"],
        evidence=[],
    )
    loaded_new = tmp_store.show(b)
    assert loaded_new.invariants == ["INV-new: must hold differently"]
    loaded_old = tmp_store.show(a)
    assert loaded_old.status == "superseded"
    # Old still has its own invariants for audit replay
    assert loaded_old.invariants == ["INV-orig: must hold"]


# ── snippet rendering ───────────────────────────────────────────────────────

def test_snippet_shows_inv_marker_when_invariants_present():
    from edp.models import Decision, utcnow

    d = Decision(
        id="DEC-0042",
        title="Focus enterprise",
        status="active",
        created_at_step=12,
        created_at_ts=utcnow(),
        created_by="agent",
        decision="…",
        invariants=["INV-1: enterprise only", "INV-2: ACV>=$50k"],
        key_constraints=["enterprise only"],
        confidence=0.85,
    )
    snip = render_snippet(d)
    assert "inv:2" in snip


def test_snippet_no_inv_marker_when_empty():
    from edp.models import Decision, utcnow

    d = Decision(
        id="DEC-0042",
        title="t",
        status="active",
        created_at_step=0,
        created_at_ts=utcnow(),
        created_by="agent",
        decision="…",
    )
    snip = render_snippet(d)
    assert "inv:" not in snip


def test_snippet_shows_alts_and_risks_markers():
    """D's R2 — surface previously-dropped alternatives + consequences in snippet."""
    from edp.models import Alternative, Decision, utcnow

    d = Decision(
        id="DEC-0042",
        title="t",
        status="active",
        created_at_step=0,
        created_at_ts=utcnow(),
        created_by="agent",
        decision="…",
        alternatives=[
            Alternative(label="Hybrid", rejected_because="doubles scope"),
            Alternative(label="SMB only", rejected_because="off-strategy"),
        ],
        consequences=["may lock out mid-market"],
    )
    snip = render_snippet(d)
    assert "alts:2" in snip
    assert "risks:1" in snip


# ── full markdown rendering ─────────────────────────────────────────────────

def test_full_markdown_has_invariants_section():
    from edp.models import Decision, utcnow

    d = Decision(
        id="DEC-0042",
        title="t",
        status="active",
        created_at_step=0,
        created_at_ts=utcnow(),
        created_by="agent",
        decision="…",
        invariants=["INV-1: x must hold", "INV-2: y must not happen"],
    )
    md = render_full_markdown(d)
    assert "## Invariants" in md
    assert "INV-1: x must hold" in md
    assert "INV-2: y must not happen" in md
    # The section also explains the contract to a human reviewer:
    assert "Machine-checkable predicates" in md


# ── primer + footer ─────────────────────────────────────────────────────────

def test_primer_mentions_edp_verify_and_inv_marker():
    assert "edp_verify" in PROTOCOL_PRIMER
    assert "inv:N" in PROTOCOL_PRIMER
    assert "alts:N" in PROTOCOL_PRIMER
    assert "risks:N" in PROTOCOL_PRIMER


def test_active_block_footer_mentions_verify():
    text = wrap_active_block(["DEC-0001 [active]\n  Title: x"], version=1, total_active=1)
    assert "edp.verify(action)" in text


# ── verifier_hook subprocess behaviour ──────────────────────────────────────

VERIFIER_HOOK = ["-m", "edp.verifier_hook"]


def _run_verifier_hook(stdin_json: str, env_extra: dict | None = None, cwd: Path | None = None):
    full_env = os.environ.copy()
    if env_extra:
        full_env.update(env_extra)
    return subprocess.run(
        [sys.executable, *VERIFIER_HOOK],
        input=stdin_json,
        capture_output=True,
        text=True,
        timeout=10,
        env=full_env,
        cwd=str(cwd) if cwd else None,
    )


def test_verifier_hook_silent_passthrough_when_no_store(tmp_path):
    """No .edp/ anywhere → exit 0, empty stdout, no error."""
    result = _run_verifier_hook(
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}}),
        env_extra={"EDP_STORE": ""},
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_verifier_hook_allows_when_no_invariants(tmp_path):
    """A store without any invariants: hook returns allow without calling the verifier (saves cost)."""
    from edp import DecisionStore

    DecisionStore.open(tmp_path / ".edp").record(
        title="legacy",
        decision="d",
        key_constraints=["soft constraint"],
        # invariants=[] by default — verifier should NOT be called
        evidence=[],
    )
    result = _run_verifier_hook(
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "x"}}),
        env_extra={"EDP_STORE": str(tmp_path / ".edp")},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    out = payload["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert "no active invariants" in out["permissionDecisionReason"].lower()


def test_verifier_hook_fail_open_when_anthropic_missing(tmp_path, monkeypatch):
    """If invariants exist but anthropic SDK is missing, hook fails open with a warning (default)."""
    from edp import DecisionStore

    DecisionStore.open(tmp_path / ".edp").record(
        title="json only",
        decision="…",
        key_constraints=[],
        invariants=["all responses MUST be JSON"],
        evidence=[],
    )
    result = _run_verifier_hook(
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "x"}}),
        env_extra={
            "EDP_STORE": str(tmp_path / ".edp"),
            # Force VerifierUnavailable by unsetting key + no anthropic install in CI
            "ANTHROPIC_API_KEY": "",
        },
    )
    payload = json.loads(result.stdout.strip())
    out = payload["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert "verifier unavailable" in out["permissionDecisionReason"].lower()


def test_verifier_hook_fail_closed_when_required_env_set(tmp_path):
    """With EDP_VERIFIER_REQUIRED=1, missing verifier dependency BLOCKS the action."""
    from edp import DecisionStore

    DecisionStore.open(tmp_path / ".edp").record(
        title="json only",
        decision="…",
        key_constraints=[],
        invariants=["all responses MUST be JSON"],
        evidence=[],
    )
    result = _run_verifier_hook(
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "x"}}),
        env_extra={
            "EDP_STORE": str(tmp_path / ".edp"),
            "ANTHROPIC_API_KEY": "",
            "EDP_VERIFIER_REQUIRED": "1",
        },
    )
    payload = json.loads(result.stdout.strip())
    out = payload["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"


# ── claude-code install --enable-verifier ───────────────────────────────────

def test_install_with_enable_verifier_writes_pretooluse_hook(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["claude-code", "install", "--enable-verifier"])
    assert result.exit_code == 0, result.output

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "PreToolUse" in settings["hooks"]
    pretool = settings["hooks"]["PreToolUse"][0]
    assert "Edit|Write|Bash|str_replace_editor" in pretool["matcher"]
    cmd = pretool["hooks"][0]["command"]
    assert "-m edp.verifier_hook" in cmd
    assert sys.executable in cmd


def test_install_without_enable_verifier_omits_pretooluse(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["claude-code", "install"])
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "PreToolUse" not in settings.get("hooks", {})


def test_uninstall_removes_pretooluse_verifier_hook(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["claude-code", "install", "--enable-verifier"])
    runner.invoke(app, ["claude-code", "uninstall"])

    settings_path = tmp_path / ".claude" / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        assert "PreToolUse" not in (settings.get("hooks") or {})


# ── CompatibilityReport model ───────────────────────────────────────────────

def test_compatibility_report_violated_requires_ids():
    r = CompatibilityReport(
        verdict="violated",
        reasoning="DEC-0042 invariant 'enterprise only' violated by SMB outreach",
        violated_decision_ids=["DEC-0042"],
    )
    assert r.verdict == "violated"
    assert "DEC-0042" in r.violated_decision_ids


def test_compatibility_report_compatible_has_empty_ids():
    r = CompatibilityReport(verdict="compatible", reasoning="all clear")
    assert r.violated_decision_ids == []
