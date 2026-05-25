"""Claude Code hook for EDP — invoked on SessionStart and UserPromptSubmit.

Reads JSON from stdin (Claude Code hook protocol), finds the nearest `.edp/`
directory walking up from `cwd`, increments a per-session monotonic version
counter, calls `edp inject --version N`, and emits the resulting active block
as `hookSpecificOutput.additionalContext`.

Designed to be idempotent and fail-soft:
- If no `.edp/` is found in the project tree, exits 0 silently — no injection.
- If `edp` is not installed or fails, exits 0 silently — does not break the session.
- The version counter is stored as a side file at `.edp/.session_version` and
  bumped per hook invocation. Together with the spec-mandated precedence line
  this defeats the additionalContext accumulation bug (claude-code#40216).

Invocation: `python -m edp.hook SessionStart` (or `UserPromptSubmit`). The
`edp claude-code install` CLI subcommand writes this into `.claude/settings.json`
automatically — no manual path resolution required.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def find_edp_root(start: Path) -> Optional[Path]:
    """Walk upward from `start`; return the first directory containing `.edp/`."""
    for p in [start, *start.parents]:
        if (p / ".edp").is_dir():
            return p
    return None


def next_version(version_file: Path) -> int:
    """Read+increment+write the monotonic version counter."""
    try:
        current = int(version_file.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        current = 0
    new = current + 1
    try:
        version_file.write_text(str(new))
    except OSError:
        # If we can't persist, version stays the same on next call — that's
        # still OK functionally, just less ideal for accumulation defence.
        pass
    return new


def emit_additional_context(event_name: str, text: str) -> None:
    """Write the Claude Code hook output JSON to stdout."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")


def detect_event_name(stdin_payload: dict) -> str:
    """Pull the hook event name from Claude Code's stdin JSON; default safely."""
    # Claude Code passes the event name in various keys across versions; try a few.
    for key in ("hook_event_name", "hookEventName", "event_name", "event"):
        if key in stdin_payload and isinstance(stdin_payload[key], str):
            return stdin_payload[key]
    # Fallback: caller can pass via argv[1]
    if len(sys.argv) >= 2:
        return sys.argv[1]
    return "UserPromptSubmit"


def main() -> int:
    # Read stdin (may be empty for some hook events / dry runs)
    try:
        raw = sys.stdin.read()
        stdin_json = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        stdin_json = {}

    event_name = detect_event_name(stdin_json)

    # Locate the EDP store. Prefer EDP_STORE env if set, else walk up from cwd.
    env_store = os.environ.get("EDP_STORE")
    if env_store:
        edp_dir = Path(env_store)
        root = edp_dir.parent
        if not edp_dir.is_dir():
            return 0
    else:
        root = find_edp_root(Path.cwd())
        if root is None:
            return 0  # no EDP store in this project — silent passthrough
        edp_dir = root / ".edp"

    # Resolve how to invoke the edp CLI.
    # Priority: EDP_BIN env override → `edp` on PATH → `python -m edp.cli`
    # (which works whenever the hook's interpreter has edp importable).
    edp_invocation: Optional[list[str]] = None
    env_bin = os.environ.get("EDP_BIN")
    if env_bin and Path(env_bin).is_file():
        edp_invocation = [env_bin]
    else:
        which_edp = shutil.which("edp")
        if which_edp:
            edp_invocation = [which_edp]
        else:
            # Last resort: invoke through this Python (works if edp is importable here)
            try:
                import edp  # noqa: F401
                edp_invocation = [sys.executable, "-m", "edp.cli"]
            except ImportError:
                edp_invocation = None

    if edp_invocation is None:
        # No reachable edp install — silently skip; do not break the user's session
        return 0

    version = next_version(edp_dir / ".session_version")

    # Include the protocol primer ONLY in SessionStart blocks — once-per-session
    # onboarding so an agent that has never used EDP discovers the four tools
    # and autonomous stance without per-project CLAUDE.md. UserPromptSubmit
    # injects without primer to keep per-turn token cost minimal.
    inject_args = ["inject", "--store", str(edp_dir), "--version", str(version)]
    if event_name == "SessionStart":
        inject_args.append("--primer")

    try:
        result = subprocess.run(
            edp_invocation + inject_args,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0  # fail-soft

    if result.returncode != 0 or not result.stdout.strip():
        return 0

    emit_additional_context(event_name, result.stdout.rstrip("\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
