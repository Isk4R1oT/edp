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
def serve(
    store_path: Optional[str] = typer.Option(None, "--store"),
) -> None:
    """Run the FastMCP server (stdio transport)."""
    from edp.server import create_server

    server = create_server(store_path or DEFAULT_STORE_DIR)
    server.run()


if __name__ == "__main__":
    app()
