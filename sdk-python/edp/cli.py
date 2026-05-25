"""Typer-based CLI: `edp init / record / list / show / inject / supersede / due / serve`."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from edp.selector import get_active_block
from edp.store import DEFAULT_STORE_DIR, DecisionNotFound, DecisionStore
from edp.render import render_full_markdown

app = typer.Typer(
    name="edp",
    help="Explicit Decision Protocol — manage agent decisions on the command line.",
    no_args_is_help=True,
)


def _store(store_path: Optional[str] = None) -> DecisionStore:
    path = store_path or os.environ.get("EDP_STORE", DEFAULT_STORE_DIR)
    return DecisionStore.open(path)


def _actor() -> str:
    return os.environ.get("EDP_ACTOR", "human:cli")


# ── Commands ──────────────────────────────────────────────────────────────────


@app.command()
def init(
    path: str = typer.Option(DEFAULT_STORE_DIR, "--path", help="Where to create .edp/"),
) -> None:
    """Initialize an EDP store in the given path (default: ./.edp)."""
    store = DecisionStore.open(path)
    typer.echo(f"Initialized EDP store at {store.db_path.parent}/")


@app.command()
def record(
    title: str = typer.Option(..., "--title", help="One-line imperative title (≤120 chars)"),
    decision: str = typer.Option(..., "--decision", help="The actual decision statement"),
    constraint: list[str] = typer.Option(
        [], "--constraint", help="Key constraint (repeatable, ≤140 chars each)"
    ),
    trigger: list[str] = typer.Option(
        [], "--trigger", help="Revision condition (event-based; repeatable, ≤200 chars each)"
    ),
    evidence: list[str] = typer.Option(
        [], "--evidence", help="Stable index handle (repeatable)"
    ),
    tag: list[str] = typer.Option([], "--tag", help="Tag (repeatable)"),
    confidence: float = typer.Option(0.7, "--confidence", min=0.0, max=1.0),
    step: int = typer.Option(0, "--step", help="The session step / turn number"),
    review_due: Optional[int] = typer.Option(None, "--review-due", help="step at which to re-review"),
    provisional: bool = typer.Option(False, "--provisional"),
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Record a new decision; prints the assigned DEC-NNNN id."""
    store = _store(store_path)
    dec_id = store.record(
        title=title,
        decision=decision,
        key_constraints=constraint,
        revision_conditions=trigger,
        evidence=evidence,
        tags=tag,
        confidence=confidence,
        actor=_actor(),
        step=step,
        review_due_at_step=review_due,
        provisional=provisional,
    )
    # store.record() projects markdown automatically (since CRIT-3 fix)
    typer.echo(dec_id)


@app.command()
def supersede(
    old_id: str = typer.Argument(..., help="The decision being superseded (DEC-NNNN)"),
    title: str = typer.Option(..., "--title"),
    decision: str = typer.Option(..., "--decision"),
    constraint: list[str] = typer.Option([], "--constraint"),
    trigger: list[str] = typer.Option([], "--trigger", help="Revision condition (event-based)"),
    evidence: list[str] = typer.Option([], "--evidence"),
    confidence: float = typer.Option(0.7, "--confidence", min=0.0, max=1.0),
    step: int = typer.Option(0, "--step"),
    review_due: Optional[int] = typer.Option(None, "--review-due"),
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Atomically supersede an existing decision; prints the new id."""
    store = _store(store_path)
    new_id = store.supersede(
        old_id,
        title=title,
        decision=decision,
        key_constraints=constraint,
        revision_conditions=trigger,
        evidence=evidence,
        confidence=confidence,
        actor=_actor(),
        step=step,
        review_due_at_step=review_due,
    )
    # store.supersede() projects both new and old markdown automatically (since CRIT-3 fix)
    typer.echo(new_id)


@app.command(name="list")
def list_(
    active: bool = typer.Option(False, "--active", help="Show only active decisions"),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag"),
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """List decisions in the store."""
    store = _store(store_path)
    if active:
        records = store.list_active(tag=tag)
    elif status:
        records = store.list(status=status, tag=tag)  # type: ignore[arg-type]
    else:
        records = store.list(tag=tag)
    if not records:
        typer.echo("(no decisions)")
        return
    for d in records:
        conf = f" conf={d.confidence:.2g}" if d.confidence is not None else ""
        prov = " [provisional]" if d.provisional else ""
        typer.echo(f"{d.id} [{d.status}]{conf}{prov}  {d.title}")


@app.command()
def show(
    decision_id: str = typer.Argument(...),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of markdown"),
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Show the full body of one decision."""
    store = _store(store_path)
    try:
        dec = store.show(decision_id)
    except DecisionNotFound as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=2)
    if as_json:
        typer.echo(json.dumps(dec.model_dump(mode="json"), indent=2))
    else:
        typer.echo(render_full_markdown(dec))


@app.command()
def inject(
    version: int = typer.Option(1, "--version", help="Monotonic block version (see §4.2)"),
    tag: list[str] = typer.Option([], "--tag", help="Context tags to scope active block"),
    budget: int = typer.Option(2000, "--budget", help="Token budget for the block"),
    primer: bool = typer.Option(False, "--primer", help="Prepend the EDP protocol primer (recommended for first-injection-per-session)"),
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Print the <edp:active> block to stdout. Designed for harness hook subprocesses."""
    from edp.selector import SelectorPolicy

    store = _store(store_path)
    result = get_active_block(
        store,
        version=version,
        context_tags=tag or None,
        policy=SelectorPolicy(token_budget=budget),
        include_primer=primer,
    )
    sys.stdout.write(result.text)
    sys.stdout.write("\n")


@app.command()
def due(
    step: int = typer.Argument(..., help="Current step number"),
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """List active decisions whose review_due_at_step ≤ given step."""
    store = _store(store_path)
    for d in store.due(step):
        typer.echo(f"{d.id} due=step:{d.review_due_at_step}  {d.title}")


@app.command()
def events(
    decision_id: Optional[str] = typer.Option(None, "--decision", help="Filter to one decision"),
    limit: int = typer.Option(20, "--limit", min=1, max=1000),
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Read from the append-only event log, newest first."""
    store = _store(store_path)
    rows = store.events(decision_id=decision_id, limit=limit)
    if not rows:
        typer.echo("(no events)")
        return
    for e in rows:
        typer.echo(
            f"#{e.event_id:>5}  {e.ts.isoformat(timespec='seconds')}  "
            f"{e.actor:<22}  {e.op:<14}  {e.decision_id}"
        )


@app.command()
def checkpoint(
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Force a WAL checkpoint (TRUNCATE). Long-lived owners should call periodically."""
    store = _store(store_path)
    store.checkpoint(truncate=True)
    typer.echo("OK")


@app.command()
def serve(
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Run the FastMCP server (stdio transport)."""
    from edp.server import create_server

    server = create_server(store_path or DEFAULT_STORE_DIR)
    server.run()


# ── Claude Code integration ───────────────────────────────────────────────────

claude_code_app = typer.Typer(
    name="claude-code",
    help="Claude Code integration — install/uninstall the EDP hook + MCP server + slash commands.",
    no_args_is_help=True,
)
app.add_typer(claude_code_app, name="claude-code")


def _settings_json(python_bin: str, *, enable_verifier: bool = False) -> dict:
    """Build the .claude/settings.json content for SessionStart + UserPromptSubmit hooks.

    If enable_verifier=True, also adds a PreToolUse hook on write-class tools
    (Edit|Write|Bash|str_replace_editor) that invokes the EDP verifier per spec
    §3.6 (v0.2). The verifier requires the [verifier] extra + ANTHROPIC_API_KEY;
    it fails open by default (set EDP_VERIFIER_REQUIRED=1 to fail closed).
    """
    config: dict = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": f"{python_bin} -m edp.hook SessionStart"}
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": f"{python_bin} -m edp.hook UserPromptSubmit"}
                    ],
                }
            ],
        }
    }
    if enable_verifier:
        config["hooks"]["PreToolUse"] = [
            {
                "matcher": "Edit|Write|Bash|str_replace_editor",
                "hooks": [
                    {"type": "command", "command": f"{python_bin} -m edp.verifier_hook"}
                ],
            }
        ]
    return config


def _mcp_json(store_path: str) -> dict:
    """Build the .claude/.mcp.json content registering the edp-mcp-server."""
    return {
        "mcpServers": {
            "edp": {
                "command": "edp-mcp-server",
                "args": [],
                "env": {"EDP_STORE": store_path},
            }
        }
    }


def _merge_hooks(existing: dict, ours: dict) -> dict:
    """Merge our hooks block into an existing settings.json, leaving other top-level keys intact.

    Conflict policy: if a SessionStart or UserPromptSubmit hooks entry already exists,
    we DO NOT touch it — the user has their own setup; return existing unchanged.
    The caller decides whether to error or warn.
    """
    out = dict(existing)
    out_hooks = dict(out.get("hooks") or {})
    for event, entries in ours["hooks"].items():
        if event not in out_hooks:
            out_hooks[event] = entries
    out["hooks"] = out_hooks
    return out


def _has_our_hook(existing: dict, event: str) -> bool:
    """True if an existing settings.json already has an EDP-style hook for the given event."""
    for entry in (existing.get("hooks") or {}).get(event, []):
        for h in entry.get("hooks", []):
            cmd = h.get("command") or ""
            if (
                "edp.hook" in cmd
                or "edp_hook.py" in cmd
                or "edp.verifier_hook" in cmd
            ):
                return True
    return False


@claude_code_app.command("install")
def claude_code_install(
    target: Path = typer.Option(
        Path(".claude"),
        "--target",
        "-t",
        help="Where to write .claude/ config (default: ./.claude)",
    ),
    store_path: str = typer.Option(
        "${PWD}/.edp",
        "--store",
        help="EDP_STORE value for the MCP server (default: ${PWD}/.edp — resolved by Claude Code)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing settings.json hooks even if they already reference EDP",
    ),
    init: bool = typer.Option(
        True,
        "--init/--no-init",
        help="Run `edp init` to create .edp/ if it does not exist (default: yes)",
    ),
    enable_verifier: bool = typer.Option(
        False,
        "--enable-verifier",
        help=(
            "Install the pre-action verifier hook (spec §3.6 v0.2). Requires "
            "'pip install explicit-decision-protocol[verifier]' + "
            "ANTHROPIC_API_KEY. Fails open by default (set EDP_VERIFIER_REQUIRED=1 "
            "in the hook env to fail closed)."
        ),
    ),
) -> None:
    """Install the EDP hook + MCP server + slash commands into a Claude Code project.

    Writes three things:
      - target/settings.json          — SessionStart + UserPromptSubmit hooks (python -m edp.hook)
      - target/.mcp.json              — registers edp-mcp-server
      - target/commands/edp-*.md      — six /edp-* slash commands

    Idempotent: re-running merges with existing config instead of overwriting. Hooks the user
    already configured for SessionStart / UserPromptSubmit are left alone (use --force to replace).

    After install, start `claude` from the project root. On the first turn the agent sees the
    protocol primer + the (empty or populated) active block.
    """
    from importlib.resources import files as resource_files
    import shutil as _shutil

    # 1. Ensure .edp/ exists (unless --no-init)
    edp_dir = Path(".edp")
    if not edp_dir.is_dir():
        if init:
            DecisionStore.open(edp_dir)
            typer.echo(f"✓ Created EDP store at {edp_dir}/")
        else:
            typer.secho(
                f"⚠ .edp/ does not exist at {edp_dir.resolve()} and --no-init was passed. "
                "Run `edp init` manually or omit --no-init.",
                fg=typer.colors.YELLOW,
                err=True,
            )

    # 2. Create target dirs
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    commands_target = target / "commands"
    commands_target.mkdir(exist_ok=True)

    # 3. Write settings.json — merge with existing if present
    python_bin = sys.executable
    settings_path = target / "settings.json"
    new_settings = _settings_json(python_bin, enable_verifier=enable_verifier)
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError as e:
            typer.secho(
                f"✗ Existing {settings_path} is not valid JSON: {e}. Aborting.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)
        has_session = _has_our_hook(existing, "SessionStart")
        has_prompt = _has_our_hook(existing, "UserPromptSubmit")
        if (has_session or has_prompt) and not force:
            typer.secho(
                f"✓ {settings_path} already has EDP hooks — left unchanged (use --force to replace)",
                fg=typer.colors.GREEN,
            )
        else:
            merged = _merge_hooks(existing, new_settings) if not force else {**existing, **new_settings}
            settings_path.write_text(json.dumps(merged, indent=2) + "\n")
            typer.echo(f"✓ Updated {settings_path}")
    else:
        settings_path.write_text(json.dumps(new_settings, indent=2) + "\n")
        typer.echo(f"✓ Wrote {settings_path}")

    # 4. Write .mcp.json — merge with existing
    mcp_path = target / ".mcp.json"
    new_mcp = _mcp_json(store_path)
    if mcp_path.exists():
        try:
            existing_mcp = json.loads(mcp_path.read_text())
        except json.JSONDecodeError as e:
            typer.secho(
                f"✗ Existing {mcp_path} is not valid JSON: {e}. Aborting.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)
        existing_servers = dict(existing_mcp.get("mcpServers") or {})
        if "edp" in existing_servers and not force:
            typer.secho(
                f"✓ {mcp_path} already registers an `edp` MCP server — left unchanged (use --force to replace)",
                fg=typer.colors.GREEN,
            )
        else:
            existing_servers["edp"] = new_mcp["mcpServers"]["edp"]
            existing_mcp["mcpServers"] = existing_servers
            mcp_path.write_text(json.dumps(existing_mcp, indent=2) + "\n")
            typer.echo(f"✓ Updated {mcp_path}")
    else:
        mcp_path.write_text(json.dumps(new_mcp, indent=2) + "\n")
        typer.echo(f"✓ Wrote {mcp_path}")

    # 5. Copy slash commands from package data
    commands_pkg = resource_files("edp") / "commands"
    copied = 0
    skipped = 0
    for cmd in commands_pkg.iterdir():
        if not cmd.name.endswith(".md"):
            continue
        dest = commands_target / cmd.name
        if dest.exists() and not force:
            skipped += 1
            continue
        # importlib.resources.files returns a Traversable; read text then write
        dest.write_text(cmd.read_text(encoding="utf-8"))
        copied += 1
    if copied:
        typer.echo(f"✓ Installed {copied} slash command(s) to {commands_target}/")
    if skipped:
        typer.secho(
            f"  ({skipped} already present — use --force to overwrite)",
            fg=typer.colors.YELLOW,
        )

    # 6. Verification hint
    typer.echo()
    typer.secho("Installed. Next steps:", fg=typer.colors.GREEN, bold=True)
    typer.echo("  1. Start `claude` from this project root")
    typer.echo("  2. Try `/edp-list` to verify the MCP server connected")
    typer.echo("  3. Ask the agent: \"What does the active EDP block say? Quote it verbatim.\"")
    typer.echo()
    typer.echo(f"Hook command in {settings_path.name}:")
    typer.echo(f"  {python_bin} -m edp.hook ...")
    if enable_verifier:
        typer.echo()
        typer.secho(
            "Verifier hook installed (PreToolUse).",
            fg=typer.colors.CYAN,
            bold=True,
        )
        typer.echo("  - Matches Edit | Write | Bash | str_replace_editor")
        typer.echo("  - Requires `pip install explicit-decision-protocol[verifier]`")
        typer.echo("  - Requires ANTHROPIC_API_KEY in env")
        typer.echo("  - Fail-open by default; set EDP_VERIFIER_REQUIRED=1 to fail closed")
        typer.echo("  - Verifier runs only when at least one active decision has invariants")


@claude_code_app.command("uninstall")
def claude_code_uninstall(
    target: Path = typer.Option(
        Path(".claude"),
        "--target",
        "-t",
        help="Path to the .claude/ config to remove EDP from (default: ./.claude)",
    ),
) -> None:
    """Remove EDP hooks, MCP server registration, and /edp-* slash commands from a project.

    Does NOT delete .edp/ — your decisions are preserved.
    """
    target = target.resolve()
    if not target.is_dir():
        typer.echo(f"Nothing to do — {target} does not exist.")
        return

    # Remove our hooks from settings.json (leave other hooks alone)
    settings_path = target / "settings.json"
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            typer.secho(f"⚠ {settings_path} is not valid JSON — left untouched", fg=typer.colors.YELLOW)
        else:
            hooks_block = dict(existing.get("hooks") or {})
            changed = False
            for event in ("SessionStart", "UserPromptSubmit", "PreToolUse"):
                if event not in hooks_block:
                    continue
                kept = []
                for entry in hooks_block[event]:
                    surviving_hooks = [
                        h for h in entry.get("hooks", [])
                        if "edp.hook" not in (h.get("command") or "")
                        and "edp_hook.py" not in (h.get("command") or "")
                        and "edp.verifier_hook" not in (h.get("command") or "")
                    ]
                    if surviving_hooks:
                        entry["hooks"] = surviving_hooks
                        kept.append(entry)
                    else:
                        changed = True
                if kept:
                    hooks_block[event] = kept
                else:
                    hooks_block.pop(event, None)
                    changed = True
            if changed:
                if hooks_block:
                    existing["hooks"] = hooks_block
                else:
                    existing.pop("hooks", None)
                settings_path.write_text(json.dumps(existing, indent=2) + "\n")
                typer.echo(f"✓ Removed EDP hooks from {settings_path}")

    # Remove `edp` MCP server from .mcp.json
    mcp_path = target / ".mcp.json"
    if mcp_path.exists():
        try:
            existing_mcp = json.loads(mcp_path.read_text())
        except json.JSONDecodeError:
            typer.secho(f"⚠ {mcp_path} is not valid JSON — left untouched", fg=typer.colors.YELLOW)
        else:
            servers = dict(existing_mcp.get("mcpServers") or {})
            if "edp" in servers:
                servers.pop("edp")
                if servers:
                    existing_mcp["mcpServers"] = servers
                else:
                    existing_mcp.pop("mcpServers", None)
                mcp_path.write_text(json.dumps(existing_mcp, indent=2) + "\n")
                typer.echo(f"✓ Removed `edp` from {mcp_path}")

    # Remove slash commands
    commands_dir = target / "commands"
    if commands_dir.is_dir():
        removed = 0
        for f in commands_dir.glob("edp-*.md"):
            f.unlink()
            removed += 1
        if removed:
            typer.echo(f"✓ Removed {removed} /edp-* slash command file(s) from {commands_dir}")

    typer.echo()
    typer.secho("Uninstalled. .edp/ store left in place — your decisions are preserved.", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
