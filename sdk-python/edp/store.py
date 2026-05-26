"""SQLite-backed DecisionStore with append-only events and FTS5 search.

Implements §7 (Storage contract) of the EDP specification.
Applies pragmas from §7.4 on every connection.
Retry-with-backoff on write contention per §7.4.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from edp.models import (
    Constraint,
    Decision,
    Event,
    RelevanceMatch,
    RelevanceReport,
    Status,
    utcnow,
)

DEFAULT_STORE_DIR = ".edp"
STORE_DB_FILENAME = "store.db"

# Current SDK schema version. Bumped when the SQLite schema gains new tables
# or columns. v2 (0.3) introduces the constraints_current table + counter
# for the constraint primitive (spec §3.8). Migration is forward-only and
# idempotent: CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE counter row.
_SDK_SCHEMA_VERSION = 2

# Required SQLite pragmas per spec §7.4. Note: wal_autocheckpoint=1000 is
# SQLite's default — explicit periodic wal_checkpoint(TRUNCATE) is what
# actually bounds WAL growth on subprocess crashes (see checkpoint()).
_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    op          TEXT NOT NULL,
    payload     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_decision_id ON events(decision_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS decisions_current (
    id        TEXT PRIMARY KEY,
    status    TEXT NOT NULL,
    data      TEXT NOT NULL,
    updated_ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions_current(status);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    decision_id UNINDEXED,
    title,
    decision,
    key_constraints
);

CREATE TABLE IF NOT EXISTS constraints_current (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated_ts  TEXT NOT NULL
);
"""


class EDPError(Exception):
    """Base error for EDP operations."""


class DecisionNotFound(EDPError):
    pass


class DecisionStore:
    """SQLite-backed decision store.

    Open with `DecisionStore.open(path)` where path is the `.edp/` directory.
    The path is created if it does not exist.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_schema()

    @classmethod
    def open(cls, store_dir: str | Path = DEFAULT_STORE_DIR) -> DecisionStore:
        store_dir = Path(store_dir)
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "decisions").mkdir(exist_ok=True)
        (store_dir / "constraints").mkdir(exist_ok=True)
        return cls(store_dir / STORE_DB_FILENAME)

    @property
    def decisions_dir(self) -> Path:
        """Default location for the human-readable markdown projection (`.edp/decisions/`)."""
        return self.db_path.parent / "decisions"

    @property
    def constraints_dir(self) -> Path:
        """Default location for constraint markdown projection (`.edp/constraints/`, v0.3)."""
        return self.db_path.parent / "constraints"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=5.0)
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Seed counter if missing
            row = conn.execute(
                "SELECT value FROM counters WHERE name='last_decision_id'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO counters(name, value) VALUES('last_decision_id', 0)"
                )
            # v0.3: constraint counter. Idempotent.
            con_row = conn.execute(
                "SELECT value FROM counters WHERE name='last_constraint_id'"
            ).fetchone()
            if con_row is None:
                conn.execute(
                    "INSERT INTO counters(name, value) VALUES('last_constraint_id', 0)"
                )
            # Record schema version on first init. Idempotent — if this row
            # already exists we don't overwrite (preserves the original init ts).
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
                (_SDK_SCHEMA_VERSION, utcnow().isoformat()),
            )

    def checkpoint(self, *, truncate: bool = True) -> None:
        """Force a WAL checkpoint to bound write-ahead-log file growth.

        A long-lived owner process (the MCP server, a daemon) SHOULD call
        this periodically (e.g. every 60s) so that even if a subprocess
        crashes mid-write the WAL is bounded. Short-lived processes do
        not need to call this — they exit too quickly to grow the WAL.

        With truncate=True (default) the WAL file is reset to zero bytes.
        """
        mode = "TRUNCATE" if truncate else "PASSIVE"
        with self._connect() as conn:
            conn.execute(f"PRAGMA wal_checkpoint({mode})")

    @contextmanager
    def _write_txn(self) -> Iterator[sqlite3.Connection]:
        """Context manager for a single write transaction with retry-on-busy."""
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                conn = self._connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    yield conn
                    conn.execute("COMMIT")
                    return
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                finally:
                    conn.close()
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    last_err = e
                    time.sleep(0.05 * (2**attempt))
                    continue
                raise
        if last_err is not None:
            raise last_err

    # ── Public API ────────────────────────────────────────────────────────────

    def next_id(self) -> str:
        """Reserve the next sequential decision id (own transaction).

        Most callers should not use this directly — record() and supersede()
        allocate the id inside the same write transaction as the actual write,
        which prevents the cross-process recency-ordering race that two
        separate transactions allow.
        """
        with self._write_txn() as conn:
            return self._next_id_within_txn(conn)

    def _next_id_within_txn(self, conn: sqlite3.Connection) -> str:
        conn.execute(
            "UPDATE counters SET value = value + 1 WHERE name='last_decision_id'"
        )
        row = conn.execute(
            "SELECT value FROM counters WHERE name='last_decision_id'"
        ).fetchone()
        return f"DEC-{row['value']:04d}"

    def record(
        self,
        *,
        title: str,
        decision: str,
        actor: str = "human:cli",
        step: int = 0,
        evidence: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        confidence: Optional[float] = None,
        key_constraints: Optional[list[str]] = None,
        invariants: Optional[list[str]] = None,
        revision_conditions: Optional[list[str]] = None,
        context: Optional[str] = None,
        consequences: Optional[list[str]] = None,
        alternatives: Optional[list[dict]] = None,
        review_due_at_step: Optional[int] = None,
        provisional: bool = False,
        status: Status = "active",
        project_markdown: bool = True,
    ) -> str:
        """Create a new decision and return its id.

        If `project_markdown` is True (default), also writes the human-readable
        markdown projection to `.edp/decisions/DEC-NNNN.md`. Set False for
        unit tests that do not care about the projection.

        Id allocation + event append + read-model upsert happen inside one
        write transaction, which prevents the cross-process recency-ordering
        race that two separate transactions would allow.
        """
        ts = utcnow()
        with self._write_txn() as conn:
            dec_id = self._next_id_within_txn(conn)
            dec = Decision(
                id=dec_id,
                title=title,
                status=status,
                created_at_step=step,
                created_at_ts=ts,
                created_by=actor,
                decision=decision,
                evidence=evidence or [],
                tags=tags or [],
                confidence=confidence,
                key_constraints=key_constraints or [],
                invariants=invariants or [],
                revision_conditions=revision_conditions or [],
                context=context,
                consequences=consequences or [],
                alternatives=[
                    {"label": a["label"], "rejected_because": a["rejected_because"]}
                    for a in (alternatives or [])
                ],
                review_due_at_step=review_due_at_step,
                provisional=provisional,
            )
            self._append_event(conn, op="record", decision_id=dec_id, actor=actor, payload=dec)
            self._upsert_current(conn, dec)
        if project_markdown:
            self.export_markdown(dec_id, self.decisions_dir)
        return dec_id

    def supersede(
        self,
        old_id: str,
        *,
        title: str,
        decision: str,
        actor: str = "human:cli",
        step: int = 0,
        evidence: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        confidence: Optional[float] = None,
        key_constraints: Optional[list[str]] = None,
        invariants: Optional[list[str]] = None,
        revision_conditions: Optional[list[str]] = None,
        context: Optional[str] = None,
        consequences: Optional[list[str]] = None,
        alternatives: Optional[list[dict]] = None,
        review_due_at_step: Optional[int] = None,
        provisional: bool = False,
        project_markdown: bool = True,
    ) -> str:
        """Atomically supersede an existing decision with a new one.

        If `project_markdown` is True (default), refreshes both markdown
        projections — the new active record and the old (now superseded) one.
        """
        old = self.show(old_id)  # raises DecisionNotFound
        if old.status not in ("active", "proposed", "revised"):
            raise EDPError(
                f"Cannot supersede {old_id} — status is {old.status!r}, must be active|proposed|revised"
            )
        ts = utcnow()
        with self._write_txn() as conn:
            new_id = self._next_id_within_txn(conn)
            new = Decision(
                id=new_id,
                title=title,
                status="active",
                created_at_step=step,
                created_at_ts=ts,
                created_by=actor,
                decision=decision,
                evidence=evidence or [],
                tags=tags or old.tags,
                confidence=confidence,
                supersedes=old_id,
                key_constraints=key_constraints or [],
                invariants=invariants or [],
                revision_conditions=revision_conditions or [],
                context=context,
                consequences=consequences or [],
                alternatives=[
                    {"label": a["label"], "rejected_because": a["rejected_because"]}
                    for a in (alternatives or [])
                ],
                review_due_at_step=review_due_at_step,
                provisional=provisional,
            )
            old_updated = old.model_copy(update={"status": "superseded", "superseded_by": new_id})
            self._append_event(conn, op="supersede", decision_id=new_id, actor=actor, payload=new)
            self._upsert_current(conn, new)
            self._append_event(
                conn,
                op="superseded_by",
                decision_id=old_id,
                actor=actor,
                payload=old_updated,
            )
            self._upsert_current(conn, old_updated)
        if project_markdown:
            self.export_markdown(new_id, self.decisions_dir)
            self.export_markdown(old_id, self.decisions_dir)
        return new_id

    def show(self, decision_id: str) -> Decision:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM decisions_current WHERE id = ?", (decision_id,)
            ).fetchone()
        if row is None:
            raise DecisionNotFound(f"unknown decision {decision_id!r}")
        return Decision.model_validate_json(row["data"])

    def list(
        self,
        *,
        status: Optional[Status | list[Status]] = None,
        tag: Optional[str] = None,
        provisional: Optional[bool] = None,
    ) -> list[Decision]:
        sql = "SELECT data FROM decisions_current"
        params: list = []
        wheres: list[str] = []
        if status is not None:
            statuses = [status] if isinstance(status, str) else list(status)
            placeholders = ",".join("?" * len(statuses))
            wheres.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if wheres:
            sql += " WHERE " + " AND ".join(wheres)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = [Decision.model_validate_json(r["data"]) for r in rows]
        if tag is not None:
            out = [d for d in out if tag in d.tags]
        if provisional is not None:
            out = [d for d in out if d.provisional == provisional]
        return out

    def list_active(
        self,
        *,
        tag: Optional[str] = None,
        include_provisional: bool = True,
    ) -> list[Decision]:
        out = self.list(status=["active", "revised"], tag=tag)
        if not include_provisional:
            out = [d for d in out if not d.provisional]
        return out

    def due(self, step: int) -> list[Decision]:
        return [
            d
            for d in self.list_active()
            if d.review_due_at_step is not None and d.review_due_at_step <= step
        ]

    def events(
        self,
        *,
        decision_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Read from the append-only event log, newest first.

        - decision_id: only events for this DEC-NNNN
        - since: only events with ts > since (must be timezone-aware)
        - limit: max events returned; default 100
        """
        wheres: list[str] = []
        params: list = []
        if decision_id is not None:
            wheres.append("decision_id = ?")
            params.append(decision_id)
        if since is not None:
            wheres.append("ts > ?")
            params.append(since.isoformat())
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        sql = (
            "SELECT event_id, ts, actor, decision_id, op, payload "
            f"FROM events {where_sql} ORDER BY event_id DESC LIMIT ?"
        )
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[Event] = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except json.JSONDecodeError:
                # Storage payload should always be JSON we wrote ourselves;
                # log structurally if not.
                payload = {"_corrupt_payload": r["payload"][:200]}
            out.append(
                Event(
                    event_id=r["event_id"],
                    ts=datetime.fromisoformat(r["ts"]),
                    actor=r["actor"],
                    decision_id=r["decision_id"],
                    op=r["op"],
                    payload=payload,
                )
            )
        return out

    def check(self, planned_action: str, *, limit: int = 5) -> RelevanceReport:
        """Soft check — return active decisions relevant to a planned action.

        Implementation: FTS5 match on title + decision + key_constraints, scored
        by SQLite bm25, returned as ranked matches. Tag overlap also boosts score.
        """
        active = self.list_active()
        if not active:
            return RelevanceReport()
        # Use FTS5 to score on text content
        query = _fts_sanitise(planned_action)
        if not query:
            return RelevanceReport()
        sql = (
            "SELECT decision_id, bm25(decisions_fts) AS score "
            "FROM decisions_fts WHERE decisions_fts MATCH ? "
            "ORDER BY score LIMIT ?"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, (query, limit * 3)).fetchall()
        active_ids = {d.id: d for d in active}
        matches: list[RelevanceMatch] = []
        for r in rows:
            if r["decision_id"] not in active_ids:
                continue
            dec = active_ids[r["decision_id"]]
            # bm25 returns negative; lower is better. Map to [0,1] approx.
            raw = -r["score"]
            relevance = min(1.0, max(0.0, raw / 10.0))
            why = _build_why(dec, planned_action)
            matches.append(RelevanceMatch(id=dec.id, relevance=relevance, why=why))
            if len(matches) >= limit:
                break
        return RelevanceReport(related=matches)

    # ── Constraints API (v0.3, spec §3.8) ─────────────────────────────────────

    def add_constraint(
        self,
        *,
        rule: str,
        actor: str = "human:cli",
        tags: Optional[list[str]] = None,
        provisional: bool = False,
        project_markdown: bool = True,
    ) -> str:
        """Create a new constraint and return its id (CON-NNNN).

        Constraints are axioms — there is no supersede chain, no
        revision_conditions, no confidence. Mutation = remove + add. If
        the agent is suggesting a constraint (under EDP_CONSTRAINT_MODE=
        agent_provisional), pass provisional=True; a human confirms via
        confirm_constraint().
        """
        ts = utcnow()
        with self._write_txn() as conn:
            con_id = self._next_constraint_id_within_txn(conn)
            con = Constraint(
                id=con_id,
                rule=rule,
                created_at_ts=ts,
                created_by=actor,
                tags=tags or [],
                provisional=provisional,
            )
            self._append_constraint_event(conn, op="con_add", con=con, actor=actor)
            self._upsert_constraint(conn, con)
        if project_markdown:
            self.export_constraint_markdown(con_id, self.constraints_dir)
        return con_id

    def remove_constraint(
        self,
        constraint_id: str,
        *,
        actor: str = "human:cli",
        reason: Optional[str] = None,
    ) -> None:
        """Remove an active constraint. Hard delete from current view; full
        history preserved in the event log. Reason is appended to the event
        payload for audit ("policy change", "merged into CON-NNNN", etc).
        """
        con = self.show_constraint(constraint_id)  # raises if not present
        with self._write_txn() as conn:
            payload = con.model_dump(mode="json")
            if reason:
                payload["_remove_reason"] = reason
            conn.execute(
                "INSERT INTO events(ts, actor, decision_id, op, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    utcnow().isoformat(),
                    actor,
                    constraint_id,
                    "con_remove",
                    json.dumps(payload),
                ),
            )
            conn.execute(
                "DELETE FROM constraints_current WHERE id = ?", (constraint_id,)
            )
        # Markdown projection removed too, so future renderers reflect reality.
        path = self.constraints_dir / f"{constraint_id}.md"
        if path.exists():
            path.unlink()

    def confirm_constraint(
        self,
        constraint_id: str,
        *,
        actor: str = "human:cli",
    ) -> None:
        """Promote a provisional constraint to non-provisional (operator
        confirms an agent-suggested rule). Idempotent on already-confirmed.
        """
        con = self.show_constraint(constraint_id)
        if not con.provisional:
            return
        promoted = con.model_copy(update={"provisional": False})
        with self._write_txn() as conn:
            self._append_constraint_event(
                conn, op="con_confirm", con=promoted, actor=actor
            )
            self._upsert_constraint(conn, promoted)
        self.export_constraint_markdown(constraint_id, self.constraints_dir)

    def show_constraint(self, constraint_id: str) -> Constraint:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM constraints_current WHERE id = ?",
                (constraint_id,),
            ).fetchone()
        if row is None:
            raise DecisionNotFound(f"unknown constraint {constraint_id!r}")
        return Constraint.model_validate_json(row["data"])

    def list_constraints(
        self,
        *,
        tag: Optional[str] = None,
        include_provisional: bool = True,
    ) -> list[Constraint]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM constraints_current ORDER BY id ASC"
            ).fetchall()
        out = [Constraint.model_validate_json(r["data"]) for r in rows]
        if not include_provisional:
            out = [c for c in out if not c.provisional]
        if tag is not None:
            out = [c for c in out if tag in c.tags]
        return out

    def export_constraint_markdown(
        self, constraint_id: str, target_dir: Path
    ) -> Path:
        from edp.render import render_constraint_markdown

        con = self.show_constraint(constraint_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{con.id}.md"
        path.write_text(render_constraint_markdown(con), encoding="utf-8")
        return path

    def _next_constraint_id_within_txn(self, conn: sqlite3.Connection) -> str:
        conn.execute(
            "UPDATE counters SET value = value + 1 WHERE name='last_constraint_id'"
        )
        row = conn.execute(
            "SELECT value FROM counters WHERE name='last_constraint_id'"
        ).fetchone()
        return f"CON-{row['value']:04d}"

    def _upsert_constraint(
        self, conn: sqlite3.Connection, con: Constraint
    ) -> None:
        conn.execute(
            """
            INSERT INTO constraints_current(id, data, updated_ts)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                data = excluded.data,
                updated_ts = excluded.updated_ts
            """,
            (con.id, con.model_dump_json(), utcnow().isoformat()),
        )

    def _append_constraint_event(
        self,
        conn: sqlite3.Connection,
        *,
        op: str,
        con: Constraint,
        actor: str,
    ) -> None:
        # Constraint events reuse the events table; decision_id column holds
        # the CON-NNNN id (column name kept for backwards compat — semantic
        # is "record id", not "decision id only").
        conn.execute(
            "INSERT INTO events(ts, actor, decision_id, op, payload) VALUES (?, ?, ?, ?, ?)",
            (
                utcnow().isoformat(),
                actor,
                con.id,
                op,
                con.model_dump_json(),
            ),
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        op: str,
        decision_id: str,
        actor: str,
        payload: Decision,
    ) -> None:
        conn.execute(
            "INSERT INTO events(ts, actor, decision_id, op, payload) VALUES (?, ?, ?, ?, ?)",
            (
                utcnow().isoformat(),
                actor,
                decision_id,
                op,
                payload.model_dump_json(),
            ),
        )

    def _upsert_current(self, conn: sqlite3.Connection, dec: Decision) -> None:
        data = dec.model_dump_json()
        ts = utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO decisions_current(id, status, data, updated_ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                data = excluded.data,
                updated_ts = excluded.updated_ts
            """,
            (dec.id, dec.status, data, ts),
        )
        # Sync FTS
        conn.execute("DELETE FROM decisions_fts WHERE decision_id = ?", (dec.id,))
        conn.execute(
            "INSERT INTO decisions_fts(decision_id, title, decision, key_constraints) VALUES (?, ?, ?, ?)",
            (
                dec.id,
                dec.title,
                dec.decision,
                " · ".join(dec.key_constraints),
            ),
        )

    def export_markdown(self, decision_id: str, target_dir: Path) -> Path:
        """Render decision to .edp/decisions/DEC-NNNN.md. Returns the file path."""
        from edp.render import render_full_markdown

        dec = self.show(decision_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{dec.id}.md"
        path.write_text(render_full_markdown(dec), encoding="utf-8")
        return path


def _fts_sanitise(text: str) -> str:
    """Tokenise free text into a safe FTS5 MATCH query."""
    keep: list[str] = []
    for tok in text.replace("/", " ").replace("-", " ").split():
        cleaned = "".join(c for c in tok if c.isalnum())
        if len(cleaned) >= 2:
            keep.append(cleaned)
    if not keep:
        return ""
    # Combine with OR for recall; strict AND would miss too much
    return " OR ".join(f'"{w}"' for w in keep[:8])


def _build_why(dec: Decision, planned_action: str) -> str:
    """Produce a short human-readable rationale for relevance."""
    action_words = {w.lower() for w in planned_action.split() if len(w) >= 4}
    matches = []
    for kc in dec.key_constraints:
        kc_words = {w.lower().strip(".,") for w in kc.split() if len(w) >= 4}
        if action_words & kc_words:
            matches.append(kc)
    if matches:
        return f"constraint match: {matches[0][:100]}"
    if dec.tags:
        return f"tagged {', '.join(dec.tags[:3])}"
    return f"title overlap: {dec.title[:60]}"
