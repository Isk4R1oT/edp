# Explicit Decision Protocol — Specification

**Version:** `edp/2026-05-24` (v0.1)
**Status:** v0.1 frozen. Subsequent additions are non-breaking under the same date until a breaking change requires a new version date. Breaking changes expected before v1.0.

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
| `confidence` | number, 0.0–1.0 | Calibrated confidence at write time. See §3.4 |
| `supersedes` | string, `DEC-NNNN` or null | Previous decision this one replaces |
| `superseded_by` | string, `DEC-NNNN` or null | Set on the previous record when this one supersedes it |
| `review_due_at_step` | integer or null | Step at which this decision should be re-confirmed. See §3.5 |
| `key_constraints` | array of string, each ≤140 chars | Human-readable constraints surfaced in the snippet block. See §3.6 |
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

### 3.4 Confidence — calibration discipline

`confidence` is a number on `[0.0, 1.0]`, not a category. Categories (`high`/`medium`/`low`) are explicitly forbidden because they prevent calibration analysis.

Implementations and operators SHOULD treat these patterns as red flags:

- An agent that writes `confidence = 1.0` (or any single fixed value) on every record. This is a signal the agent is not calibrating. Catch it in an eval pipeline that checks confidence distribution across a window of decisions.
- An agent whose confidence does not correlate with downstream success on the same class of decisions. Confidence is supposed to predict reliability, not perform it.

Implementations MAY auto-decay confidence: when `review_due_at_step` is reached and the decision has not been re-confirmed, decrement `confidence` by `0.1` and append a note to `review_history`. This is RECOMMENDED but not required for v0.1.

### 3.5 `review_due_at_step` — non-binding default rule

`review_due_at_step` is optional, but SHOULD be set for any decision that is not strictly tactical. Decisions without a review trigger silently accumulate stale evidence on long sessions.

A sensible default for implementations to suggest at write time:

- `created_at_step + 100` for business or scope decisions
- `created_at_step + 50` for technical / architectural decisions
- `created_at_step + 20` for tactical decisions

These are heuristics, not normative. Operators MAY tune per project.

### 3.6 `key_constraints` — naming and scope note

In Architecture Decision Record literature (Nygard 2011, MADR) this field is conventionally called **`invariants`** and is required to be programmatically assertable — a runtime predicate.

EDP v0.1 deliberately renames this field to **`key_constraints`** and relaxes the requirement: these are human-readable constraints displayed to the agent in the snippet block, **not** runtime predicates. The agent reads them, the agent may call `check()` to consult them before risky actions, but no proxy or verifier enforces them on tool calls.

Runtime invariant assertion (with a verifier gating tool calls) is a known follow-on extension. It is deferred from v0.1 because (a) gating introduces a measured verifier tax on long-horizon success (see [arXiv:2603.19328](https://arxiv.org/abs/2603.19328)) and (b) the visibility primitive — making decisions present in the agent's working context — is the load-bearing intervention that should land first.

### 3.7 Decision-worthiness — what should be recorded

EDP is not a logbook. Recording every micro-choice as a decision floods the active block, drowns out the signal, and trains the agent to ignore it. Recording nothing produces the silent drift EDP exists to prevent.

A record SHOULD be created when at least two of the following are true:

1. **Multi-turn consequence.** The choice constrains work that will happen in subsequent turns or sessions. Not a one-shot action.
2. **Constraint-shaped.** The choice can be summarised as one or more `key_constraints` of ≤140 chars that future actions can be checked against (via `check()`).
3. **Hard to re-derive.** The rationale depends on context that will be expensive to reconstruct later (user-stated preference, research finding, performance data).
4. **Reversibility-relevant.** The cost of acting against this choice later is non-trivial — it requires rework, undoes user trust, or has external side effects.

A record SHOULD NOT be created for: variable names, single-file refactors, ad-hoc clarifications, parameters of a single function call, or anything that would not change behaviour two turns later.

When in doubt, ask: *"Will another agent / future-me, three days from now, regret not seeing this decision?"* If yes, record. If unsure, lean toward not recording — under-recording is recoverable (record it later when it becomes relevant); over-recording is corrosive (the active block becomes noise).

Implementations MAY enforce a soft heuristic — e.g. warn if `key_constraints` is empty, prompt for confirmation if `decision` is shorter than 80 characters — but MUST NOT block valid records.

---

## 4. The active block (snippet injection)

The selector produces an **active block** that adapters inject into the agent's context on every turn (or per harness lifecycle).

### 4.1 Block format

```
<edp:active version="7">
DEC-0042 [active] conf=0.85 due=step:100
  Title: Focus competitive analysis on enterprise B2B (500+ emp)
  Key constraints: enterprise-only · ACV>=$50k · exclude SMB
DEC-0043 [active] conf=0.9
  Title: Use LangGraph for orchestration, not raw chains
  Key constraints: multi-step flows must use StateGraph
DEC-0044 [revised] conf=0.7 → see DEC-0051
  Title: Vector store choice was Pinecone, now pgvector

Active: 12 · `edp.show(id)` for full body · `edp.check(action)` before risky moves
If multiple <edp:active> blocks appear in this context, use only version="7" — earlier blocks are stale.
</edp:active>
```

### 4.2 Block constraints

- Block MUST be wrapped in `<edp:active version="N">…</edp:active>` for unambiguous detection. `version` MUST be a monotonically increasing integer per session.
- The block MUST include the explicit precedence line at the bottom: *"If multiple `<edp:active>` blocks appear in this context, use only version=`N` — earlier blocks are stale."* This is a hard requirement, not a recommendation. Several mainstream harnesses (notably Claude Code via [`UserPromptSubmit` accumulation #40216](https://github.com/anthropics/claude-code/issues/40216)) accumulate `additionalContext` in the transcript with no API to rewrite or delete prior content. The precedence line is the only available mitigation.
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

When trimming, the selector MUST preserve `id`, `status`, and `key_constraints` for every included decision. `title` is the second-priority field. `confidence` and `due` markers are dropped first if a single record must be shortened. Whole records are dropped before any record is shown without its `key_constraints`.

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

### 6.1 Subtask boundary review

At every subtask boundary (or, in harnesses without first-class subtasks, at a configurable step interval), the adapter SHOULD:

1. Query `due(current_step)` to get decisions whose `review_due_at_step` ≤ current step.
2. Surface them to the agent with a structured "please re-confirm or supersede these" prompt.
3. For decisions that are neither re-confirmed nor superseded within a configurable grace window, decrement `confidence` by `0.1` and append a `review_history` entry noting the decay.

This closes the "stale active decisions" failure mode where long sessions accumulate decisions whose original context has shifted entirely.

### 6.2 Context compaction

When the harness compacts context (e.g. Claude Code auto-compaction at the context window boundary), adapters MUST ensure:

1. The full active block survives compaction. Compaction MUST NOT silently drop the `<edp:active>` block — this is the single most-cited cause of constraint loss in production (see [claude-code#19471](https://github.com/anthropics/claude-code/issues/19471)).
2. `key_constraints` of every active decision land in the anchor preamble of the post-compaction context (i.e. at the top, where attention is densest).
3. `superseded` and `deprecated` records do NOT need to survive compaction — they live in the durable store and can be retrieved on demand via `show(id)`.

Adapters that cannot inspect the compaction event SHOULD re-inject the active block on the first turn after compaction is detected (by a context-size drop or harness signal).

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

### 7.4 SQLite pragmas — required

EDP stores are expected to be accessed from multiple processes simultaneously: a long-lived MCP server / middleware in the agent process, and short-lived subprocesses spawned by harness hooks (e.g. Claude Code `UserPromptSubmit` hook reading the active block on every turn). SQLite's default settings are not safe for this pattern and will surface as silent `SQLITE_BUSY` errors.

Every implementation MUST apply these pragmas on every connection:

```sql
PRAGMA journal_mode = WAL;            -- allow concurrent readers + one writer
PRAGMA busy_timeout = 5000;           -- 5s grace before SQLITE_BUSY (Python default is 0)
PRAGMA synchronous = NORMAL;          -- full sync is overkill for append-only events
PRAGMA foreign_keys = ON;             -- enforce referential integrity on supersede chains
```

Every write transaction MUST:

- Be wrapped in a retry-with-backoff loop (2–3 retries, 50ms initial, exponential).
- Complete in sub-millisecond time. Long-running aggregations belong in read connections.
- Use `BEGIN IMMEDIATE` (not `BEGIN DEFERRED`) so contention surfaces at transaction start, not at first write.
- Allocate the new decision id (via the `last_decision_id` counter) **inside the same transaction** as the corresponding event append + read-model upsert. Splitting id allocation into a separate transaction creates a cross-process race that can invert recency ordering.

A long-lived owner process (the MCP server, a middleware daemon) SHOULD additionally call `PRAGMA wal_checkpoint(TRUNCATE)` periodically — every 60 seconds is a safe default. This bounds the WAL file when short-lived subprocess writers (e.g. Claude Code hook scripts) crash mid-write. Reference implementations expose this as `store.checkpoint(truncate=True)`. Short-lived processes do not need to checkpoint — they exit before the WAL can grow.

Note: setting `PRAGMA wal_autocheckpoint = 1000` is a no-op (it is SQLite's default); explicit periodic checkpoint from a long-lived owner is the only reliable bound on WAL growth under subprocess-crash patterns.

References: [SQLite concurrent writes and busy errors](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/), [Abusing SQLite to handle concurrency](https://blog.skypilot.co/abusing-sqlite-to-handle-concurrency/).

---

## 8. Adapter contract

An EDP adapter is responsible for delivering the active block to a specific harness on the harness's natural extension point.

### 8.1 Adapter MUST

- Read the active block from a configured EDP store on each invocation.
- Place the block in a location where the LLM will see it on every turn (system prompt prefix, user-turn prefix, or harness-specific equivalent).
- Surface the four core tools to the agent, in whatever native tool-format the harness uses.
- Emit blocks with a monotonically increasing `version="N"` per session, and include the precedence line required by §4.2 in every emitted block.
- Apply the SQLite pragmas required by §7.4 on every connection opened against the store.

### 8.2 Harness-specific MUSTs

These are non-negotiable for the named adapter implementations because of documented harness behaviour. Other adapter implementations SHOULD apply the spirit of these rules.

**Claude Code adapter** MUST ship in **two forms**:
- A standalone `.claude/hooks/` config that the user can drop into a project (works today).
- A plugin manifest form (works once [claude-code#16538](https://github.com/anthropics/claude-code/issues/16538) is fixed — currently `hookSpecificOutput.additionalContext` is silently dropped for hooks delivered via plugin manifest).

Until #16538 is resolved, the standalone form is the supported default; the plugin form is shipped opportunistically as a convenience for teams using marketplace distribution.

**LangGraph adapter** MUST execute its `@before_model` middleware **before** LangChain's built-in `SummarizationMiddleware`. Both middlewares write to `state["messages"]` at the same insertion point; if summarization runs first, the EDP block can be summarised away before the model sees it. The adapter package MUST ship an integration test asserting correct ordering when both middlewares are registered simultaneously. See LangChain v1.1 middleware [changelog](https://changelog.langchain.com/announcements/langchain-1-1) for context.

### 8.3 Adapter SHOULD

- Place the block at a stable position (top of system prompt, ideally) so prompt caching is preserved across turns.
- Pin to stdio transport on Windows until [fastmcp#4192](https://github.com/jlowin/fastmcp/issues/4192) is resolved (HTTP transport leaks SSE tasks per session, deadlocks after ~12 sessions on Windows).
- Where the harness exposes a "subtask boundary" signal, implement §6.1 (subtask boundary review).

### 8.4 Known adapters (v0.1 roadmap)

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

## 11. Resolved for v0.1

These design questions were considered during the drafting of v0.1 and resolved as follows. Each entry is binding for any implementation that claims conformance to `edp/2026-05-24`.

| Question | Resolution | Rationale |
|---|---|---|
| Should `confidence` be a freeform number, or quantised buckets? | **Freeform `[0.0, 1.0]`** | Buckets prevent calibration analysis; freeform allows downstream eval pipelines to measure calibration quality (§3.4). |
| Should `review_due_at_step` be step-based, time-based, or both? | **Step-based only in v0.1** | Step is the unit the agent reasons about directly. Time-based review is a candidate for a future extension when needed. |
| What is the right default for agent-authored `provisional` decisions? | **Include in active block with `[provisional]` status marker; selector MAY hide them via config** | Visible-but-distinguished is the honest default: humans can audit before promotion, agent gets feedback on its own proposals. Hiding is a per-project policy choice. |
| Should adapters be required to expose `list()` and `history()`? | **MAY, not MUST** | The four core tools (§5.1–§5.4) are sufficient for the protocol contract. Helpers belong to implementations. |
| File layout: `.edp/` at project root, or namespaced under harness conventions? | **`.edp/` at project root** | EDP is harness-agnostic; placing under `.claude/edp/` would imply ownership by Claude Code. Project-root keeps the store visible to all adapters equally. |

Implementation-specific choices (Python SDK PyPI name, CLI surface, import name, etc.) are documented in `sdk-python/README.md` and `pyproject.toml`. They are not binding on the protocol — alternative implementations are free to make different choices.

---

## 12. Anti-patterns (what tends to go wrong)

EDP exists because the following practices all silently fail. Avoid them in any EDP-conformant implementation or agent integration.

1. **One large `Decisions.md` for everything.** Does not retrieve well, hides the supersede graph, and tempts in-place edits. EDP requires one record per decision, append-only.
2. **Decisions without `key_constraints`.** A decision body in prose tonces in attention dilution within tens of turns. The snippet block surfaces `key_constraints` precisely to keep the operative content visible after the prose has been compacted away.
3. **Free-form `key_constraints` ("important to consider enterprise").** If the constraint cannot be summarised in ≤140 chars in a form an agent can match against an action, it is an intention, not a constraint. Move it to `consequences`.
4. **Editing an `active` decision.** Breaks the audit trail. Always supersede, even for small wording changes.
5. **`confidence = 1.0` on every record.** Calibration failure. Catch in an eval pipeline that checks the confidence distribution across a recent window.
6. **`evidence = "from earlier in the conversation"`.** Useless on the second session. Only stable handles (`@session_log/...`, `@artifacts/path:line`, `@memory/...`) — anything else is reconstructable hallucination.
7. **No `review_due_at_step`.** Decisions silently rot. Always set one, even if the default heuristic is wrong by 30%.
8. **Skipping `alternatives`.** Tens of turns later the agent re-derives a rejected alternative because the rejection rationale is not in context. Always record what was considered and why it lost.
9. **Treating the snippet block as a system reminder the model "should" follow.** Treat it as **shown context** that the agent reads and may act on; use `check()` for any risky action regardless. Hope is not a strategy.
10. **Adding fields ad hoc to the JSON record.** Extensions must go through the spec process (open an issue, motivate the field, propose the schema change). Otherwise the protocol fragments and adapters break.

## 13. Reference implementations

| Component | Language | Status | Known limitations |
|---|---|---|---|
| Core SDK | Python (FastMCP 3.x) | scaffolding | Multi-process write contention — see §7.4; pin to stdio on Windows ([fastmcp#4192](https://github.com/jlowin/fastmcp/issues/4192)) |
| MCP-server adapter | Python (thin wrapper over core) | planned | Resources are pull-only in every mainstream MCP client; per-turn auto-injection requires a harness-native adapter, not MCP alone |
| Claude Code adapter | Hooks (standalone) + Plugin manifest (when available) | planned | Plugin-form `SessionStart` `additionalContext` silently dropped ([claude-code#16538](https://github.com/anthropics/claude-code/issues/16538)); use standalone `.claude/hooks/` form until fixed |
| LangGraph adapter | Python (`@before_model` middleware) | planned | Must run before `SummarizationMiddleware` — see §8.2; requires LangChain ≥ 1.1 |
| Vercel AI SDK adapter | TypeScript (`wrapLanguageModel` middleware) | planned | Structured-output schema validation gap ([vercel/ai#9594](https://github.com/vercel/ai/issues/9594)) — own validator required |
| Cursor watcher | Python (daemon regenerates `.cursor/rules/edp-active.mdc`) | post-v0.1 | Rules are static — refresh latency on the order of file-watcher poll interval |
| LiteLLM proxy adapter | Python (`async_pre_call_hook`) | post-v0.1 | Catch-all for any direct API call; provider-specific system-prompt semantics differ |

See `sdk-python/` and `adapters/` for current state. The public issue [#1 in the project repo](https://github.com/Isk4R1oT/edp/issues/1) tracks the live status of these limitations.

---

## 14. References

The EDP record schema and supersede semantics derive from established Architecture Decision Record practice, extended with primitives needed for an agent-readable lifecycle.

- Nygard, M. *Documenting Architecture Decisions* (2011) — the original ADR
- [MADR](https://adr.github.io/madr/) — Markdown ADR template
- Microsoft Azure Well-Architected Framework — ADR section
- Anthropic Engineering, *Effective context engineering for AI agents* — [link](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Anthropic Engineering, *Effective harnesses for long-running agents* — [link](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- MCP — [Model Context Protocol](https://modelcontextprotocol.io/) — version policy, JSON-RPC tool surface
- A2A — [Agent-to-Agent Protocol](https://a2a-protocol.org/) — AgentCard discovery pattern (deferred to v1.0)

See [`docs/evidence.md`](docs/evidence.md) for the full citation arsenal motivating the design (22 sources across academic findings, GitHub issues, HN signal, and SWE-bench analysis).

---

*This is a v0.1 draft. Inputs welcome. Open issues at the project repository.*
