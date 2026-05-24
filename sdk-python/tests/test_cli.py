"""End-to-end CLI tests via typer.testing."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from edp.cli import app

runner = CliRunner()


def test_init_creates_store(tmp_path: Path):
    result = runner.invoke(app, ["init", "--path", str(tmp_path / ".edp")])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".edp" / "store.db").exists()


def test_record_inject_supersede_roundtrip(tmp_path: Path):
    store = tmp_path / ".edp"
    args = ["--store", str(store)]

    # record
    r = runner.invoke(
        app,
        [
            "record",
            "--title", "Use pgvector for vector storage",
            "--decision", "All vector storage uses pgvector in the existing Postgres.",
            "--constraint", "no new infra deps",
            "--constraint", "cosine and L2 supported",
            "--evidence", "@session_log/step_5/research",
            "--tag", "infra",
            "--confidence", "0.85",
            *args,
        ],
    )
    assert r.exit_code == 0, r.stdout
    dec_id = r.stdout.strip()
    assert dec_id == "DEC-0001"
    # markdown projection
    assert (store / "decisions" / "DEC-0001.md").exists()

    # inject
    r = runner.invoke(app, ["inject", "--version", "1", *args])
    assert r.exit_code == 0, r.stdout
    assert '<edp:active version="1">' in r.stdout
    assert "DEC-0001" in r.stdout
    assert "no new infra deps" in r.stdout
    assert 'use only version="1"' in r.stdout

    # list active
    r = runner.invoke(app, ["list", "--active", *args])
    assert r.exit_code == 0, r.stdout
    assert "DEC-0001" in r.stdout
    assert "[active]" in r.stdout

    # show
    r = runner.invoke(app, ["show", "DEC-0001", *args])
    assert r.exit_code == 0, r.stdout
    assert "id: DEC-0001" in r.stdout
    assert "## Decision" in r.stdout

    # supersede
    r = runner.invoke(
        app,
        [
            "supersede", "DEC-0001",
            "--title", "Vector storage: pgvector with cosine only",
            "--decision", "pgvector cosine only; L2 dropped.",
            "--constraint", "cosine only",
            "--evidence", "@session_log/step_40/perf",
            "--confidence", "0.9",
            *args,
        ],
    )
    assert r.exit_code == 0, r.stdout
    new_id = r.stdout.strip()
    assert new_id == "DEC-0002"
    # both markdown files updated
    assert (store / "decisions" / "DEC-0002.md").exists()
    # old projection updated to status=superseded
    old_md = (store / "decisions" / "DEC-0001.md").read_text()
    assert "status: superseded" in old_md
    assert "superseded_by: DEC-0002" in old_md

    # inject again — should show new as active, old as superseded
    r = runner.invoke(app, ["inject", "--version", "2", *args])
    assert r.exit_code == 0, r.stdout
    assert "DEC-0002 [active]" in r.stdout
    assert "DEC-0001 [superseded]" in r.stdout
    assert "→ see DEC-0002" in r.stdout


def test_due_command(tmp_path: Path):
    store = tmp_path / ".edp"
    args = ["--store", str(store)]
    runner.invoke(
        app,
        [
            "record",
            "--title", "Early-review decision",
            "--decision", "d",
            "--review-due", "10",
            *args,
        ],
    )
    runner.invoke(
        app,
        [
            "record",
            "--title", "Late-review decision",
            "--decision", "d",
            "--review-due", "100",
            *args,
        ],
    )
    r = runner.invoke(app, ["due", "20", *args])
    assert r.exit_code == 0, r.stdout
    assert "DEC-0001" in r.stdout
    assert "DEC-0002" not in r.stdout


def test_show_unknown_decision_fails(tmp_path: Path):
    store = tmp_path / ".edp"
    args = ["--store", str(store)]
    runner.invoke(app, ["init", "--path", str(store)])
    r = runner.invoke(app, ["show", "DEC-9999", *args])
    assert r.exit_code != 0
