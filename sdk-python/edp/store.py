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
from pathlib import Path
from typing import Iterator, Optional

from edp.models import (
    Decision,
    RelevanceMatch,
    RelevanceReport,
    Status,
    utcnow,
)

DEFAULT_STORE_DIR = ".edp"
STORE_DB_FILENAME = "store.db"

# Required SQLite pragmas per spec §7.4
_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA wal_autocheckpoint = 1000",
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

CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    decision_id UNINDEXED,
    title,
    decision,
    key_constraints
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
        return cls(store_dir / STORE_DB_FILENAME)

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
        """Reserve the next sequential decision id."""
        with self._write_txn() as conn:
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
        context: Optional[str] = None,
        consequences: Optional[list[str]] = None,
        alternatives: Optional[list[dict]] = None,
        review_due_at_step: Optional[int] = None,
        provisional: bool = False,
        status: Status = "active",
    ) -> str:
        """Create a new decision and return its id."""
        dec_id = self.next_id()
        ts = utcnow()
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
            context=context,
            consequences=consequences or [],
            alternatives=[
                {"label": a["label"], "rejected_because": a["rejected_because"]}
                for a in (alternatives or [])
            ],
            review_due_at_step=review_due_at_step,
            provisional=provisional,
        )
        self._write_decision(dec, op="record", actor=actor)
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
        context: Optional[str] = None,
        consequences: Optional[list[str]] = None,
        alternatives: Optional[list[dict]] = None,
        review_due_at_step: Optional[int] = None,
        provisional: bool = False,
    ) -> str:
        """Atomically supersede an existing decision with a new one."""
        old = self.show(old_id)  # raises DecisionNotFound
        if old.status not in ("active", "proposed", "revised"):
            raise EDPError(
                f"Cannot supersede {old_id} — status is {old.status!r}, must be active|proposed|revised"
            )
        new_id = self.next_id()
        ts = utcnow()
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
            context=context,
            consequences=consequences or [],
            alternatives=[
                {"label": a["label"], "rejected_because": a["rejected_because"]}
                for a in (alternatives or [])
            ],
            review_due_at_step=review_due_at_step,
            provisional=provisional,
        )
        # Update old record's superseded_by + status
        old_updated = old.model_copy(update={"status": "superseded", "superseded_by": new_id})

        with self._write_txn() as conn:
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

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _write_decision(self, dec: Decision, *, op: str, actor: str) -> None:
        with self._write_txn() as conn:
            self._append_event(conn, op=op, decision_id=dec.id, actor=actor, payload=dec)
            self._upsert_current(conn, dec)

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


def _build_why(dec, planned_action: str) -> str:
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
