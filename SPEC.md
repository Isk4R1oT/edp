# Explicit Decision Protocol — Specification

**Version:** `edp/2026-05-24` (v0.1, draft)
**Status:** alpha, breaking changes expected before v1.0

---

## 1. What EDP is

EDP is a specification for **structured, machine-addressable decision records** that AI agents make during long-horizon work, plus a contract for how those records are surfaced back into the agent's context window on every turn.

EDP solves one specific problem: agents make a decision early in a session, then **drift away from it** as context accumulates, the original reasoning leaves the attention window, and the constraint becomes a vague memory. EDP makes every active decision a first-class, addressable artifact the agent can see, look up, check against, and supersede explicitly.

EDP is **not** a memory system, not a runtime verification framework, and not a governance product. It is a small protocol focused on one mechanism: decisions as inspectable artifacts in the agent loop.

---

## 2. Design principles

1. **Two-tier injection.** Every active decision has a tiny snippet (always in context) and a full body (retrieved on demand). The agent never carries the full body unless it asks.
2. **Decisions are append-only.** Existing records are never edited. Changes happen by writing a new record that `supersedes` the old one.
3. **Stable identifiers.** Every decision has a sequential `id` (`DEC-NNNN`) that never changes and never repeats within a project.
4. **Programmatic-readable, human-readable.** The record is structured JSON, but every field has a markdown projection so a human can read the same artifact.
5. **Harness-agnostic.** EDP defines the model and the agent-facing contract. Injection into the LLM context is delegated to per-harness adapters (Claude Code plugin, LangGraph middleware, MCP server, Cursor watcher, etc).

---

## 3. The decision record

A decision is a single immutable record with these fields.

### 3.1 Required fields

| Field | Type | Description |
|---|---|---|
| `id` | string, format `DEC-\d{4,}` | Sequential identifier, project-unique, never reused |
| `title` | string, ≤120 chars | One-line imperative statement of what is decided |
| `status` | enum | One of: `proposed`, `active`, `superseded`, `revised`, `deprecated`, `rejected` |
| `created_at_step` | integer | The turn / step in the session when this was recorded |
| `created_at_ts` | string (ISO-8601) | Wall-clock timestamp |
| `created_by` | string | Identifier of the actor (e.g. `orchestrator`, `subagent_research`, `human:igor`) |
| `decision` | string (markdown) | The actual decision statement. One decision per record. |
| `evidence` | array of string | Stable index handles, e.g. `@session_log/step_8/user_message`, `@artifacts/path/file.py:42` |

### 3.2 Optional fields

| Field | Type | Description |
|---|---|---|
| `tags` | array of string | Free-form categories used by the selector to scope active blocks |
| `confidence` | number, 0.0–1.0 | Calibrated confidence in the decision at write time |
| `supersedes` | string, `DEC-NNNN` or null | Previous decision this one replaces |
| `superseded_by` | string, `DEC-NNNN` or null | Set on the previous record when this one supersedes it |
| `review_due_at_step` | integer or null | Step at which this decision should be re-confirmed |
| `key_constraints` | array of string, each ≤140 chars | Human-readable constraints surfaced in the snippet block. **Not assertable in v0.1** — this is a contract for the agent reader, not a runtime predicate |
| `context` | string (markdown) | What facts and state led to the decision |
| `alternatives` | array of objects `{label, rejected_because}` | What was considered and rejected |
| `consequences` | array of string | What this decision enables / closes / risks |
| `review_history` | array of objects `{ts, step, note, ref}` | Append-only log of re-validations |

### 3.3 Status workflow

```
proposed ──► active ──┬──► superseded   (replaced by DEC-MMMM)
                      ├──► revised      (review_history grew, body unchanged)
                      └──► deprecated   (no longer relevant, no replacement)

rejected (was proposed, never activated)
```

`active` records participate in the active block. All other statuses are read-only history.

---

## 4. The active block (snippet injection)

The selector produces an **active block** that adapters inject into the agent's context on every turn (or per harness lifecycle).

### 4.1 Block format

```
<edp:active version="1">
DEC-0042 [active] conf=0.85 due=step:100
  Title: Focus competitive analysis on enterprise B2B (500+ emp)
  Key constraints: enterprise-only · ACV>=$50k · exclude SMB
DEC-0043 [active] conf=0.9
  Title: Use LangGraph for orchestration, not raw chains
  Key constraints: multi-step flows must use StateGraph
DEC-0044 [revised] conf=0.7 → see DEC-0051
  Title: Vector store choice was Pinecone, now pgvector

Active: 12 · `edp.show(id)` for full body · `edp.check(action)` before risky moves
</edp:active>
```

### 4.2 Block constraints

- Block MUST be wrapped in `<edp:active version="N">…</edp:active>` for unambiguous detection.
- Each snippet MUST fit in 4 lines maximum.
- Total block target: **≤2,000 tokens**. Selector trims by `recency desc`, `confidence desc` if over budget.
- The footer line MUST list the count and a one-line tool hint, so agents that did not read the upstream spec can still discover the tools.

### 4.3 Selector contract

Inputs: the full decision store + an optional context hint (current tags, current step number, current file/scope).

Output: the ordered list of decisions to include in the active block.

Default selection policy (implementations MAY override):

1. Include all `active` decisions whose `tags` intersect the context hint, OR all `active` decisions if no hint.
2. Include `revised` and `superseded` decisions only if referenced by an included `active` decision (so the agent sees the supersede pointer).
3. Order: pinned (if any) > by recency desc > by confidence desc.
4. Trim from the bottom if the block exceeds token budget. The footer reports the trimmed count.

Selectors MUST NOT use semantic / embedding search in v0.1. Tag + recency + status + FTS (on-demand only via the search tool) is sufficient and predictable. Latency target: <5ms for projects up to 10,000 decisions.

---

## 5. Agent-facing tools

These are the tools exposed to the agent, with their signatures. Implementations MUST expose at least these four. Names MAY be prefixed (e.g. `edp.show`, `edp_show`, `mcp__edp__show`) per adapter convention.

### 5.1 `show(id) -> Decision`

Returns the full body of a single decision: all fields, supersede chain, review history, evidence handles. Used when the agent needs to understand "what exactly was decided and why".

```
show("DEC-0042")
→ {
    id, title, status, decision, context, alternatives,
    consequences, key_constraints, evidence,
    supersede_chain: [{id, ts, note}, …],
    review_history: [{ts, step, note}, …]
  }
```

### 5.2 `check(planned_action) -> RelevanceReport`

Soft check: given a description of an upcoming action, return active decisions that may be relevant. **Agent-initiated, not a runtime gate.** No block, no proxy intercept. The agent decides what to do with the report.

```
check("send outreach email to SMB segment leads")
→ {
    related: [
      {id: "DEC-0042", relevance: 0.91, why: "scope restricts to enterprise"},
      {id: "DEC-0067", relevance: 0.43, why: "email cadence rule"}
    ]
  }
```

v0.1 relevance scoring: tag match + FTS over title/key_constraints/decision. No embeddings.

### 5.3 `record(...) -> id`

Creates a new decision record. Returns the assigned `DEC-NNNN`. The new record's snippet is included in the next turn's active block.

```
record({
  title: "Use pgvector instead of Pinecone for vector storage",
  decision: "All vector storage migrates to pgvector running in the existing Postgres.",
  key_constraints: ["no new infra deps", "must support cosine and L2"],
  evidence: ["@session_log/step_47/research_subagent"],
  tags: ["infra", "storage"],
  confidence: 0.8
})
→ "DEC-0051"
```

Agents SHOULD set `confidence` honestly. Decisions written by agents (not humans) MAY be marked `provisional: true` and excluded from the active block by the selector until a human confirms.

### 5.4 `supersede(old_id, new_record) -> new_id`

Atomic supersede: writes a new decision, sets the old one to `superseded`, links them both. The new decision's snippet replaces the old one in the active block.

```
supersede("DEC-0044", {
  title: "Vector store: pgvector",
  decision: "…",
  …
})
→ "DEC-0051"
```

### 5.5 Optional tools (MAY)

Implementations MAY expose:

- `list(filter) -> [DecisionSummary]` — list decisions by status/tag/step range
- `history(id) -> SupersedeChain` — walk the full supersede graph
- `due(step) -> [id]` — decisions whose `review_due_at_step` ≤ step

---

## 6. Lifecycle

```
                    record                    inject (every turn)
agent decides ──► edp.record(...) ──► snippet in <edp:active> block
                       │                          ▲
                       ▼                          │
                  append-only                 selector
                  events table                    │
                       │                          │
                       └──────► projected ────────┘
                                read model

agent (later)
    │
    ├── needs full body  ──► edp.show(id)
    ├── plans risky move ──► edp.check(action)
    └── changes mind     ──► edp.supersede(old, new) ──► next-turn block shows new
```

The agent never directly accesses storage. All access goes through the four tools. Adapters are responsible for the inject side of the loop.

---

## 7. Storage contract

Reference implementations SHOULD use an append-only event log plus a projected read model. No record is ever updated in place; status transitions are themselves events.

### 7.1 Events table (minimum)

```
events(
  event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           TEXT NOT NULL,    -- ISO-8601
  actor        TEXT NOT NULL,
  decision_id  TEXT NOT NULL,    -- DEC-NNNN
  op           TEXT NOT NULL,    -- record | supersede | revise | deprecate | reject | review
  payload      TEXT NOT NULL     -- JSON
)
```

### 7.2 Read model

A projected `decisions_current` materialised view (or a recompute on read) holds the latest state per `decision_id`. FTS5 index over `title || decision || key_constraints` for `check()` and `search`.

### 7.3 File layout (reference)

```
.edp/
  store.db                       # SQLite
  decisions/
    DEC-0042.md                  # human-readable export, one file per record
    DEC-0043.md
    …
  config.json                    # selector policy, token budget, tags
```

The markdown files are a **read-only projection** of the events. Editing them does not change the store. This enables git review while keeping the store authoritative.

---

## 8. Adapter contract

An EDP adapter is responsible for delivering the active block to a specific harness on the harness's natural extension point.

### 8.1 Adapter MUST

- Read the active block from a configured EDP store on each invocation.
- Place the block in a location where the LLM will see it on every turn (system prompt prefix, user-turn prefix, or harness-specific equivalent).
- Surface the four core tools to the agent, in whatever native tool-format the harness uses.

### 8.2 Adapter SHOULD

- Place the block at a stable position so prompt caching is preserved.
- Detect the duplicate-injection / accumulation bug present in some harnesses (e.g. Claude Code `UserPromptSubmit`) and either emit a delta or include the `version="N"` marker so the model uses only the latest block.

### 8.3 Known adapters (v0.1 roadmap)

- `adapters/claude-code-plugin/` — `UserPromptSubmit` + `SessionStart` hooks, four tools as plugin commands
- `adapters/mcp-server/` — FastMCP 3.x server, four tools, resource `decisions://active` for MCP clients that auto-fetch resources
- `adapters/cursor-watcher/` — daemon that regenerates `.cursor/rules/edp-active.mdc` on store changes (post-v0.1)
- `adapters/middleware-langgraph/` — `@before_model` middleware (post-v0.1)
- `adapters/vercel-ai/` — `wrapLanguageModel` middleware (post-v0.1)
- `adapters/litellm-proxy/` — `async_pre_call_hook` catch-all (post-v0.1)

---

## 9. Versioning

EDP uses date-stamped specification versions (`edp/2026-05-24`), not semver. This is the same convention as MCP, and avoids the trap of "is v2.1.3 a breaking change in the protocol or in the SDK".

Specification revisions live under `spec/<date>/`. Implementations declare which specification version(s) they conform to.

---

## 10. Non-goals for v0.1

EDP v0.1 explicitly does NOT cover:

- **Runtime invariant gating.** `check()` is agent-initiated, not a proxy that blocks tool calls. Out of scope for v0.1, separate extension later.
- **Semantic search.** Tag + FTS + recency is sufficient for the corpus sizes we target (hundreds, not millions). Embeddings add latency, infra, and predictability cost.
- **Remote / distributed stores.** v0.1 is local SQLite. Wire protocol (JSON-RPC handshake, capability negotiation, AgentCard discovery) deferred to v1.0.
- **Cross-project decision sharing.** One store per project.
- **Auto-elicitation of decisions.** EDP does not infer decisions from conversation. The agent (or human) must call `record()` explicitly. This is the "explicit" in the name.

---

## 11. Open questions for v0.1

These are unresolved and welcome input:

- Should `confidence` be a freeform number, or quantised buckets (0.25 / 0.5 / 0.75 / 1.0) for better calibration discipline?
- Should `review_due_at_step` be step-based, time-based, or both?
- What is the right default for `provisional` decisions written by agents — auto-include in block, auto-exclude, or include with `[provisional]` marker?
- Should adapters be required to expose `list()` and `history()`, or only the four core tools?
- File layout: `.edp/` at project root, or `.claude/edp/` to namespace under Claude Code conventions?

---

## 12. Reference implementations

| Component | Language | Status |
|---|---|---|
| Core SDK | Python (FastMCP 3.x) | scaffolding |
| MCP-server adapter | Python (thin wrapper over core) | planned |
| Claude Code plugin | TypeScript (Claude Agent SDK) | planned |

See `sdk-python/` and `adapters/` for current state.

---

*This is a v0.1 draft. Inputs welcome. Open issues at the project repository.*
