"""Unit tests for the Claude Code EDP hook.

The hook is a subprocess: it reads JSON from stdin, walks up the file tree
looking for `.edp/`, and emits Claude-Code-hook JSON to stdout. Tests below
exercise it as a subprocess (the way Claude Code itself does), not via
import — that's the contract that matters.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from edp import DecisionStore

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / "standalone" / "hooks" / "edp_hook.py"
)


def _run_hook(cwd: Path, event_name: str = "UserPromptSubmit", env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the hook script as Claude Code would."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH), event_name],
        cwd=cwd,
        input="",  # Claude Code passes JSON, but the hook is tolerant of empty stdin
        capture_output=True,
        text=True,
        timeout=10,
        env=full_env,
    )


@pytest.fixture
def project_with_store():
    """Project directory that has a .edp/ with one seeded decision."""
    tmp = Path(tempfile.mkdtemp(prefix="edp_hook_test_"))
    try:
        store = DecisionStore.open(tmp / ".edp")
        store.record(
            title="Test decision",
            decision="A test decision body.",
            key_constraints=["test constraint A", "test constraint B"],
            evidence=["@test/handle"],
            tags=["test"],
            confidence=0.8,
        )
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hook_emits_valid_json_when_store_exists(project_with_store):
    """With a .edp/ in cwd, the hook should emit a parseable hookSpecificOutput."""
    result = _run_hook(project_with_store, event_name="UserPromptSubmit")
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout.strip())
    assert "hookSpecificOutput" in payload
    out = payload["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    block = out["additionalContext"]
    # Spec §4.2 essentials
    assert '<edp:active version="1">' in block
    assert "</edp:active>" in block
    assert 'use only version="1"' in block
    # Decision content
    assert "DEC-0001" in block
    assert "test constraint A" in block


def test_hook_walks_up_to_find_edp_root(project_with_store):
    """Run from a subdirectory; hook must find the .edp/ at the project root."""
    subdir = project_with_store / "src" / "deep" / "nested"
    subdir.mkdir(parents=True, exist_ok=True)
    result = _run_hook(subdir, event_name="UserPromptSubmit")
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    block = payload["hookSpecificOutput"]["additionalContext"]
    assert "DEC-0001" in block


def test_hook_silent_when_no_store_found(tmp_path):
    """No .edp/ anywhere up the tree → exit 0, empty stdout, no error."""
    result = _run_hook(tmp_path, event_name="UserPromptSubmit")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_hook_increments_version_across_invocations(project_with_store):
    """Each invocation bumps the version counter — defeats accumulation bug."""
    r1 = _run_hook(project_with_store, event_name="UserPromptSubmit")
    r2 = _run_hook(project_with_store, event_name="UserPromptSubmit")
    r3 = _run_hook(project_with_store, event_name="UserPromptSubmit")

    v1 = json.loads(r1.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    v2 = json.loads(r2.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    v3 = json.loads(r3.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    assert 'version="1"' in v1
    assert 'version="2"' in v2
    assert 'version="3"' in v3


def test_hook_event_name_preserved(project_with_store):
    """SessionStart and UserPromptSubmit both pass through to additionalContext."""
    r1 = _run_hook(project_with_store, event_name="SessionStart")
    payload = json.loads(r1.stdout.strip())
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_hook_respects_edp_store_env(project_with_store, tmp_path):
    """When EDP_STORE env points at a specific store, the hook uses it regardless of cwd."""
    elsewhere = tmp_path / "unrelated"
    elsewhere.mkdir()
    env = {"EDP_STORE": str(project_with_store / ".edp")}
    result = _run_hook(elsewhere, event_name="UserPromptSubmit", env=env)
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    block = payload["hookSpecificOutput"]["additionalContext"]
    assert "DEC-0001" in block


def test_hook_includes_precedence_line(project_with_store):
    """The mandatory §4.2 precedence-line is present in the emitted block."""
    result = _run_hook(project_with_store, event_name="UserPromptSubmit")
    block = json.loads(result.stdout.strip())["hookSpecificOutput"]["additionalContext"]
    assert "use only version=" in block
    assert "earlier blocks are stale" in block
