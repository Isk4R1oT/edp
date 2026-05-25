from edp.selector import SelectorPolicy, get_active_block


def _record(store, **kw):
    defaults = dict(
        title="t",
        decision="d",
        key_constraints=[],
        evidence=[],
        tags=[],
        confidence=0.7,
    )
    defaults.update(kw)
    return store.record(**defaults)


def test_block_has_version_and_precedence_line(tmp_store):
    _record(tmp_store, title="a")
    result = get_active_block(tmp_store, version=7)
    assert '<edp:active version="7">' in result.text
    assert "</edp:active>" in result.text
    assert "use only version=\"7\"" in result.text
    assert "edp.show(id)" in result.text
    assert "edp.check(action)" in result.text


def test_empty_store_renders_placeholder(tmp_store):
    result = get_active_block(tmp_store, version=1)
    # v0.1.2: empty placeholder mentions edp_record to guide first-time agents
    assert "no active decisions" in result.text
    assert "edp_record" in result.text
    assert result.included == 0
    assert result.total_active == 0


def test_tag_filter(tmp_store):
    _record(tmp_store, title="orm", tags=["orm"])
    _record(tmp_store, title="api", tags=["api"])
    _record(tmp_store, title="both", tags=["orm", "api"])
    result = get_active_block(tmp_store, version=1, context_tags=["orm"])
    ids = {d.id for d in result.decisions}
    assert "DEC-0001" in ids and "DEC-0003" in ids
    assert "DEC-0002" not in ids


def test_supersede_chain_referenced_decision_included(tmp_store):
    a = _record(tmp_store, title="old", tags=["scope"])
    tmp_store.supersede(
        a,
        title="new",
        decision="d",
        key_constraints=[],
        evidence=[],
    )
    result = get_active_block(tmp_store, version=1)
    ids = {d.id for d in result.decisions}
    # New active decision is included, AND the superseded reference too
    assert "DEC-0002" in ids
    assert "DEC-0001" in ids
    assert "superseded" in result.text


def test_trim_preserves_at_least_one(tmp_store):
    """Even with a tiny budget, at least one snippet survives (we never emit truly empty when active exist)."""
    for i in range(20):
        _record(tmp_store, title=f"decision number {i} with some text to fatten")
    result = get_active_block(
        tmp_store, version=1, policy=SelectorPolicy(token_budget=80)
    )
    assert result.included >= 1
    assert result.trimmed > 0
    assert result.total_active == 20


def test_recency_ordering(tmp_store):
    a = _record(tmp_store, title="first")
    b = _record(tmp_store, title="second")
    c = _record(tmp_store, title="third")
    result = get_active_block(tmp_store, version=1)
    # Newest first
    assert result.decisions[0].id == c
    assert result.decisions[-1].id == a
