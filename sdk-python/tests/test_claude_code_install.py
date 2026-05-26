"""Tests for the `edp claude-code install` / `uninstall` CLI subcommands.

Exercises the user-facing surface: a fresh install writes the expected files,
re-install is idempotent, --force overwrites, uninstall is reversible and
leaves the EDP store + unrelated config alone.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from edp.cli import app


runner = CliRunner()


@pytest.fixture
def tmp_project(tmp_path: Path, monkeypatch):
    """Cd into a fresh empty tmp dir so cwd-relative paths resolve there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_install_fresh_writes_all_files(tmp_project):
    result = runner.invoke(app, ["claude-code", "install"])
    assert result.exit_code == 0, result.output

    # Three primary files
    assert (tmp_project / ".claude" / "settings.json").exists()
    assert (tmp_project / ".claude" / ".mcp.json").exists()

    # Seven slash commands (v0.3: + edp-constraints)
    cmd_dir = tmp_project / ".claude" / "commands"
    cmds = sorted(f.name for f in cmd_dir.glob("edp-*.md"))
    assert cmds == [
        "edp-check.md",
        "edp-constraints.md",
        "edp-events.md",
        "edp-list.md",
        "edp-record.md",
        "edp-show.md",
        "edp-supersede.md",
    ]

    # Store auto-created
    assert (tmp_project / ".edp").is_dir()


def test_install_settings_uses_python_module_invocation(tmp_project):
    """The settings.json command must use `python -m edp.hook`, not an absolute file path."""
    runner.invoke(app, ["claude-code", "install"])

    settings = json.loads((tmp_project / ".claude" / "settings.json").read_text())
    session_cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    prompt_cmd = settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]

    assert "-m edp.hook SessionStart" in session_cmd
    assert "-m edp.hook UserPromptSubmit" in prompt_cmd
    # No bare "edp_hook.py" filesystem path
    assert "edp_hook.py" not in session_cmd
    assert "edp_hook.py" not in prompt_cmd
    # Uses sys.executable so the right venv's python is invoked
    assert sys.executable in session_cmd


def test_install_mcp_json_registers_edp_server(tmp_project):
    runner.invoke(app, ["claude-code", "install"])

    mcp = json.loads((tmp_project / ".claude" / ".mcp.json").read_text())
    assert "edp" in mcp["mcpServers"]
    assert mcp["mcpServers"]["edp"]["command"] == "edp-mcp-server"
    # PWD-resolved store path
    assert "${PWD}/.edp" in mcp["mcpServers"]["edp"]["env"]["EDP_STORE"]


def test_install_is_idempotent(tmp_project):
    """Re-running install on a project that already has EDP must NOT duplicate or error."""
    r1 = runner.invoke(app, ["claude-code", "install"])
    assert r1.exit_code == 0
    settings_before = (tmp_project / ".claude" / "settings.json").read_text()

    r2 = runner.invoke(app, ["claude-code", "install"])
    assert r2.exit_code == 0
    assert "already has EDP hooks" in r2.output
    assert "already registers an `edp` MCP server" in r2.output

    settings_after = (tmp_project / ".claude" / "settings.json").read_text()
    assert settings_before == settings_after  # unchanged


def test_install_merges_with_existing_unrelated_hooks(tmp_project):
    """If the user already has a PreToolUse hook, our install must not clobber it."""
    claude_dir = tmp_project / ".claude"
    claude_dir.mkdir()
    existing = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Write", "hooks": [{"type": "command", "command": "my-formatter"}]}
            ]
        },
        "permissions": {"allow": ["Bash(ls:*)"]},
    }
    (claude_dir / "settings.json").write_text(json.dumps(existing))

    result = runner.invoke(app, ["claude-code", "install"])
    assert result.exit_code == 0

    merged = json.loads((claude_dir / "settings.json").read_text())
    # Our hooks added
    assert "SessionStart" in merged["hooks"]
    assert "UserPromptSubmit" in merged["hooks"]
    # User's hook preserved
    assert "PreToolUse" in merged["hooks"]
    assert merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "my-formatter"
    # Unrelated top-level keys preserved
    assert merged["permissions"]["allow"] == ["Bash(ls:*)"]


def test_install_no_init_skips_edp_init(tmp_project):
    """With --no-init and no pre-existing .edp/, we should not create one."""
    result = runner.invoke(app, ["claude-code", "install", "--no-init"])
    assert result.exit_code == 0
    assert not (tmp_project / ".edp").exists()
    # But .claude/ files are still written
    assert (tmp_project / ".claude" / "settings.json").exists()


def test_install_force_overwrites_existing_edp_hooks(tmp_project):
    """With --force, an existing EDP hook is replaced (not duplicated)."""
    # First install
    runner.invoke(app, ["claude-code", "install"])
    # Tamper with settings.json so we can detect overwrite
    settings_path = tmp_project / ".claude" / "settings.json"
    tampered = json.loads(settings_path.read_text())
    tampered["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "OLD-COMMAND"
    settings_path.write_text(json.dumps(tampered))

    # Re-install with --force
    result = runner.invoke(app, ["claude-code", "install", "--force"])
    assert result.exit_code == 0
    after = json.loads(settings_path.read_text())
    assert "OLD-COMMAND" not in after["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "-m edp.hook SessionStart" in after["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_install_handles_invalid_existing_settings_json(tmp_project):
    """If .claude/settings.json exists but is not valid JSON, install fails cleanly."""
    claude_dir = tmp_project / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{not valid json")

    result = runner.invoke(app, ["claude-code", "install"])
    assert result.exit_code == 1
    assert "not valid JSON" in result.output


def test_uninstall_removes_only_edp_entries(tmp_project):
    """Uninstall must remove EDP hooks/MCP entry/commands but leave other config intact."""
    # Pre-seed with user-owned + EDP-owned config
    claude_dir = tmp_project / ".claude"
    claude_dir.mkdir()
    pre_seed = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Write", "hooks": [{"type": "command", "command": "my-formatter"}]}
            ],
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": f"{sys.executable} -m edp.hook SessionStart"}
                    ],
                }
            ],
        },
        "permissions": {"allow": ["Bash(ls:*)"]},
    }
    (claude_dir / "settings.json").write_text(json.dumps(pre_seed))
    (claude_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "edp": {"command": "edp-mcp-server"},
                    "other": {"command": "other-mcp-server"},
                }
            }
        )
    )
    (claude_dir / "commands").mkdir()
    (claude_dir / "commands" / "edp-record.md").write_text("# edp-record\n")
    (claude_dir / "commands" / "my-own-cmd.md").write_text("# my-own-cmd\n")

    result = runner.invoke(app, ["claude-code", "uninstall"])
    assert result.exit_code == 0

    # SessionStart EDP hook removed; PreToolUse user hook kept
    settings_after = json.loads((claude_dir / "settings.json").read_text())
    assert "SessionStart" not in (settings_after.get("hooks") or {})
    assert settings_after["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "my-formatter"
    assert settings_after["permissions"]["allow"] == ["Bash(ls:*)"]

    # edp MCP entry removed; other MCP entry kept
    mcp_after = json.loads((claude_dir / ".mcp.json").read_text())
    assert "edp" not in mcp_after["mcpServers"]
    assert "other" in mcp_after["mcpServers"]

    # EDP slash command removed; user slash command kept
    assert not (claude_dir / "commands" / "edp-record.md").exists()
    assert (claude_dir / "commands" / "my-own-cmd.md").exists()


def test_uninstall_preserves_edp_store(tmp_project):
    """Decisions in .edp/ must survive uninstall — your work is preserved."""
    from edp import DecisionStore

    runner.invoke(app, ["claude-code", "install"])
    runner.invoke(app, ["record", "--title", "important", "--decision", "do not lose me"])

    store_db = tmp_project / ".edp" / "store.db"
    assert store_db.exists()

    # Capture the decision content (not raw bytes — SQLite internal state can shift)
    decisions_before = [(d.id, d.title) for d in DecisionStore.open(".edp").list_active()]
    assert decisions_before == [("DEC-0001", "important")]

    runner.invoke(app, ["claude-code", "uninstall"])

    assert store_db.exists()
    decisions_after = [(d.id, d.title) for d in DecisionStore.open(".edp").list_active()]
    assert decisions_after == decisions_before


def test_uninstall_on_clean_project_is_noop(tmp_project):
    """Running uninstall on a project with no .claude/ must not error."""
    result = runner.invoke(app, ["claude-code", "uninstall"])
    assert result.exit_code == 0
    assert "Nothing to do" in result.output


def test_hook_module_runs_as_python_minus_m(tmp_project, monkeypatch):
    """`python -m edp.hook` must execute the same code as the script form.

    Smoke-checks the import path; full behavioural coverage lives in
    adapters/claude-code-plugin/tests/test_hook.py which exercises the
    subprocess invocation against a real store.
    """
    from edp import hook as hook_module

    assert callable(hook_module.main)
    assert callable(hook_module.find_edp_root)
    # The module's __main__ block exists (verified by file inspection — main is
    # called when the module is run directly)
    src = Path(hook_module.__file__).read_text()
    assert 'if __name__ == "__main__":' in src
    assert "sys.exit(main())" in src
