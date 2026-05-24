# EDP in action — example session

This walkthrough shows what an agent session looks like with EDP installed via the Claude Code plugin. Decisions are recorded, surfaced in the active block on every turn, and consulted before risky actions.

The setup: a coding agent is helping refactor a small backend service. Two decisions were already recorded in prior turns:

- `DEC-0001` — "Use SQLAlchemy 2.x async-only patterns, no sync sessions"
- `DEC-0002` — "All new endpoints expose only JSON, no XML"

---

## Turn 12 — agent receives the active block

The Claude Code `UserPromptSubmit` hook injects this at the top of the turn:

```
<edp:active version="3">
DEC-0001 [active] conf=0.95
  Title: Use SQLAlchemy 2.x async-only patterns
  Key constraints: no sync sessions · all new code uses AsyncSession
DEC-0002 [active] conf=0.9
  Title: All new endpoints expose only JSON
  Key constraints: no XML serialisation · response_class=JSONResponse

Active: 2 · `edp.show(id)` for full body · `edp.check(action)` before risky moves
</edp:active>
```

User prompt: *"Add a /reports endpoint that returns the last 30 days of orders."*

---

## Turn 12 — agent reasons and acts

The agent sees both active decisions. Both are relevant: the new endpoint must be JSON and must use async SQLAlchemy. The agent does not need to ask the user about format or DB API — those questions are already settled.

It calls `edp.check` as a sanity move:

```
edp.check("add GET /reports endpoint returning JSON list of last 30 days of orders, async SQLAlchemy query")
→ {
    related: [
      {id: "DEC-0001", relevance: 0.88, why: "constrains DB access pattern"},
      {id: "DEC-0002", relevance: 0.81, why: "constrains response format"}
    ]
  }
```

Compatible. The agent writes the endpoint using `AsyncSession` and `JSONResponse`. No drift.

---

## Turn 17 — a new constraint emerges

While implementing, the agent notices the orders table is large and the user mentions a performance concern. It decides to introduce a pagination convention for all list endpoints. This is a decision worth recording — future endpoints should follow it.

```
edp.record({
  title: "All list endpoints paginate with cursor-based pagination, default limit 50",
  decision: "List endpoints accept `cursor` and `limit` query params. Limit defaults to 50, max 200. Returns `next_cursor` in response envelope.",
  key_constraints: [
    "cursor + limit query params",
    "default limit 50, max 200",
    "response envelope contains next_cursor"
  ],
  evidence: ["@session_log/turn_15/user_message", "@artifacts/services/orders.py:124"],
  tags: ["api", "pagination"],
  confidence: 0.8
})
→ "DEC-0003"
```

---

## Turn 18 — block now includes DEC-0003

The selector picks up the new record. Next turn's block:

```
<edp:active version="4">
DEC-0001 [active] conf=0.95
  Title: Use SQLAlchemy 2.x async-only patterns
  Key constraints: no sync sessions · all new code uses AsyncSession
DEC-0002 [active] conf=0.9
  Title: All new endpoints expose only JSON
  Key constraints: no XML serialisation · response_class=JSONResponse
DEC-0003 [active] conf=0.8
  Title: All list endpoints paginate with cursor-based pagination
  Key constraints: cursor + limit · default 50 max 200 · next_cursor in envelope

Active: 3 · `edp.show(id)` for full body · `edp.check(action)` before risky moves
</edp:active>
```

The agent now carries this constraint forward without re-deriving it.

---

## Turn 34 — agent is about to violate

Twenty turns later, the agent is working on an unrelated request. It is about to add a `GET /audit-events` endpoint and almost writes it as offset-based pagination because that is what came up in a code example it grep'd.

Habit pays off — it calls `edp.check` first:

```
edp.check("add GET /audit-events with offset+limit pagination returning JSON")
→ {
    related: [
      {id: "DEC-0003", relevance: 0.93, why: "list endpoints must use cursor-based pagination"},
      {id: "DEC-0002", relevance: 0.78, why: "JSON response constraint"}
    ]
  }
```

`DEC-0003` flags it. The agent fetches the full body to confirm:

```
edp.show("DEC-0003")
→ { …, decision: "List endpoints accept `cursor` and `limit`…", … }
```

It revises its plan: cursor-based pagination instead of offset. No human had to spot the drift. The decision did the work.

---

## Turn 41 — superseding

Performance testing shows that the limit ceiling of 200 was too generous for the audit-events endpoint. The team decides to drop it to 100 globally. This is a supersede, not an edit:

```
edp.supersede("DEC-0003", {
  title: "List endpoints paginate with cursor, default limit 25, max 100",
  decision: "…",
  key_constraints: [
    "cursor + limit query params",
    "default limit 25, max 100",
    "response envelope contains next_cursor"
  ],
  evidence: ["@session_log/turn_40/perf_results", "@artifacts/tests/perf/list_endpoints.md"],
  confidence: 0.85
})
→ "DEC-0004"
```

The block at turn 42:

```
<edp:active version="5">
DEC-0001 [active] conf=0.95
  Title: Use SQLAlchemy 2.x async-only patterns
  Key constraints: no sync sessions · all new code uses AsyncSession
DEC-0002 [active] conf=0.9
  Title: All new endpoints expose only JSON
  Key constraints: no XML serialisation · response_class=JSONResponse
DEC-0003 [superseded] → see DEC-0004
  Title: All list endpoints paginate with cursor-based pagination (limit 50/200)
DEC-0004 [active] conf=0.85
  Title: List endpoints paginate with cursor, default limit 25, max 100
  Key constraints: cursor + limit · default 25 max 100 · next_cursor in envelope

Active: 3 · `edp.show(id)` for full body · `edp.check(action)` before risky moves
</edp:active>
```

The supersede pointer is visible — the agent (and a human reviewer) can trace why the limit changed. Audit trail is complete; the original decision is preserved.

---

## What is and is not happening here

**Is happening:**
- Decisions are persistent and visible on every turn
- The agent can fetch full bodies for confirmation
- The agent can self-check upcoming actions against active decisions
- Supersede chains are preserved; history is not lost

**Is not happening:**
- No proxy is intercepting tool calls or blocking actions
- No semantic search, no embeddings
- No automatic decision elicitation from conversation
- No remote sync, no cross-project sharing

The agent is in charge of its own work. EDP just makes its own past decisions hard to forget.
