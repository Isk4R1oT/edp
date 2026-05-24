import pytest

from edp.store import DecisionNotFound, EDPError


def _record(store, **kw):
    defaults = dict(
        title="t",
        decision="d",
        key_constraints=["c1"],
        evidence=["@x"],
        tags=["t1"],
        confidence=0.7,
    )
    defaults.update(kw)
    return store.record(**defaults)


def test_record_and_show_roundtrip(tmp_store):
    did = _record(tmp_store, title="Use pgvector")
    assert did == "DEC-0001"
    dec = tmp_store.show(did)
    assert dec.title == "Use pgvector"
    assert dec.status == "active"
    assert dec.confidence == 0.7
    assert dec.key_constraints == ["c1"]


def test_show_unknown_raises(tmp_store):
    with pytest.raises(DecisionNotFound):
        tmp_store.show("DEC-9999")


def test_sequential_ids(tmp_store):
    ids = [_record(tmp_store, title=f"d{i}") for i in range(5)]
    assert ids == ["DEC-0001", "DEC-0002", "DEC-0003", "DEC-0004", "DEC-0005"]


def test_supersede_chain(tmp_store):
    old = _record(tmp_store, title="old")
    new = tmp_store.supersede(
        old,
        title="new",
        decision="new d",
        key_constraints=["new c"],
        evidence=["@y"],
        confidence=0.8,
    )
    old_dec = tmp_store.show(old)
    new_dec = tmp_store.show(new)
    assert old_dec.status == "superseded"
    assert old_dec.superseded_by == new
    assert new_dec.status == "active"
    assert new_dec.supersedes == old


def test_supersede_already_superseded_fails(tmp_store):
    a = _record(tmp_store, title="a")
    b = tmp_store.supersede(a, title="b", decision="d", key_constraints=[], evidence=[])
    # a is now superseded — superseding it again must fail
    with pytest.raises(EDPError):
        tmp_store.supersede(a, title="c", decision="d", key_constraints=[], evidence=[])
    # but superseding b (active) is fine
    c = tmp_store.supersede(b, title="c", decision="d", key_constraints=[], evidence=[])
    assert tmp_store.show(b).superseded_by == c


def test_list_active_excludes_superseded(tmp_store):
    a = _record(tmp_store, title="a")
    b = _record(tmp_store, title="b")
    tmp_store.supersede(a, title="a2", decision="d", key_constraints=[], evidence=[])
    active = tmp_store.list_active()
    active_ids = {d.id for d in active}
    assert a not in active_ids  # superseded
    assert b in active_ids  # still active


def test_check_finds_constraint_match(tmp_store):
    _record(
        tmp_store,
        title="Enterprise only",
        decision="Restrict to enterprise customers",
        key_constraints=["enterprise only", "ACV>=$50k"],
        tags=["scope"],
    )
    rep = tmp_store.check("send outreach to SMB segment leads")
    assert len(rep.related) >= 1
    assert rep.related[0].id == "DEC-0001"


def test_due_filter(tmp_store):
    _record(tmp_store, title="a", review_due_at_step=10)
    _record(tmp_store, title="b", review_due_at_step=50)
    _record(tmp_store, title="c")  # no due
    due = tmp_store.due(20)
    assert {d.id for d in due} == {"DEC-0001"}
    due_all = tmp_store.due(100)
    assert {d.id for d in due_all} == {"DEC-0001", "DEC-0002"}


def test_provisional_filter(tmp_store):
    _record(tmp_store, title="real")
    _record(tmp_store, title="prov", provisional=True)
    excluded = tmp_store.list_active(include_provisional=False)
    assert {d.id for d in excluded} == {"DEC-0001"}
    included = tmp_store.list_active(include_provisional=True)
    assert {d.id for d in included} == {"DEC-0001", "DEC-0002"}


def test_pragmas_applied(tmp_store):
    """Ensure spec §7.4 pragmas are actually set on connections."""
    conn = tmp_store._connect()
    try:
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        conn.close()
    assert jm == "wal"
    assert bt == 5000
    assert sync == 1  # NORMAL
    assert fk == 1


def test_event_log_append_only(tmp_store):
    """Every record/supersede should produce one or more events; events table grows monotonically."""
    conn = tmp_store._connect()
    before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    a = _record(tmp_store, title="a")
    b = _record(tmp_store, title="b")
    tmp_store.supersede(a, title="a2", decision="d", key_constraints=[], evidence=[])
    conn = tmp_store._connect()
    after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    by_dec = dict(
        conn.execute(
            "SELECT decision_id, COUNT(*) FROM events GROUP BY decision_id"
        ).fetchall()
    )
    conn.close()
    assert after == before + 4  # 2 record + 2 events for supersede (new+old)
    assert by_dec[a] == 2  # initial record + superseded_by event
    assert by_dec[b] == 1


def test_events_read_api_newest_first(tmp_store):
    """store.events() returns the append-only log newest-first with payloads parsed."""
    a = _record(tmp_store, title="a")
    b = _record(tmp_store, title="b")
    tmp_store.supersede(a, title="a2", decision="d", key_constraints=["kc"], evidence=[])

    all_events = tmp_store.events(limit=100)
    # Newest-first: supersede pair (2 events) → record(b) → record(a)
    assert len(all_events) == 4
    assert all_events[0].event_id > all_events[-1].event_id
    # Each event has a parsed payload, not a raw JSON string
    for e in all_events:
        assert isinstance(e.payload, dict)
        assert e.payload.get("id") == e.decision_id

    # Filter by decision_id
    a_events = tmp_store.events(decision_id=a)
    assert len(a_events) == 2  # record + superseded_by
    assert all(e.decision_id == a for e in a_events)

    # Limit caps results
    limited = tmp_store.events(limit=2)
    assert len(limited) == 2


def test_events_filter_by_since(tmp_store):
    from edp.models import utcnow

    _record(tmp_store, title="before")
    threshold = utcnow()
    import time as _t
    _t.sleep(0.01)  # ensure ts > threshold
    _record(tmp_store, title="after")

    after_only = tmp_store.events(since=threshold)
    titles = [e.payload.get("title") for e in after_only]
    assert "after" in titles
    assert "before" not in titles


def test_checkpoint_runs_without_error(tmp_store):
    """checkpoint() bounds WAL growth; smoke-test it executes."""
    _record(tmp_store, title="trigger wal entry")
    # Should not raise. Actual WAL truncation is observable by file size but
    # may be racy across platforms; we only verify the API contract.
    tmp_store.checkpoint(truncate=True)
    tmp_store.checkpoint(truncate=False)


def test_schema_version_recorded(tmp_store):
    """A freshly initialised store records the SDK schema version it was built under."""
    conn = tmp_store._connect()
    row = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 1


def test_record_uses_single_write_txn(tmp_store):
    """record() should allocate id and write event/projection in one transaction.

    This is a regression test for the HIGH-5 race fix in the audit. We assert
    that the events table grows by exactly 1 per record (no orphan from a
    half-failed two-txn write).
    """
    conn = tmp_store._connect()
    before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    for i in range(5):
        _record(tmp_store, title=f"d{i}")
    conn = tmp_store._connect()
    after = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    assert after - before == 5  # exactly one event per record
