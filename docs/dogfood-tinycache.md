# Dogfood — `tinycache` blank-slate trial

> **TL;DR.** Two real Claude Code sessions on an empty project. `CLAUDE.md` was
> `0 bytes`. The agent received no human instructions about EDP and no
> hand-crafted decisions in the store. In session 1 it recorded 4 decisions
> autonomously. In session 2 (different topic, same store) it superseded
> one of those decisions and recorded a new one deferring a feature
> request, citing the `revision_conditions` field of a session-1 decision
> as the technical blocker.
>
> This is the empirical claim behind every numerical statement in
> `README.md`. Everything below is reproducible.

**Date:** 2026-05-25 · **Model:** Opus 4.7 (1M ctx) · **Harness:** Claude Code via the standalone hooks adapter (`adapters/claude-code-plugin/standalone/`) · **Tested EDP version:** v0.1.2 (commit `fc72b6b`).

---

## Setup

```sh
mkdir -p /tmp/edp-blank && cd /tmp/edp-blank
touch CLAUDE.md                                 # 0 bytes, truly empty
mkdir -p src/tinycache tests
echo "" > src/tinycache/__init__.py

edp init                                        # creates .edp/
# No `edp record` seeded. Store is empty.

# Drop in the standalone Claude Code adapter — $EDP_REPO is your local
# checkout of github.com/Isk4R1oT/edp (or wherever you cloned it):
mkdir -p .claude/commands
cp $EDP_REPO/adapters/claude-code-plugin/standalone/settings.json.example .claude/settings.json
cp $EDP_REPO/adapters/claude-code-plugin/standalone/.mcp.json.example .claude/.mcp.json
cp $EDP_REPO/adapters/claude-code-plugin/standalone/commands/*.md .claude/commands/
# Edit the two example paths to point at $EDP_REPO/adapters/claude-code-plugin/standalone/.

claude                                          # session 1 starts
```

The `SessionStart` hook injects the **protocol primer** (~280 tokens of
prose explaining the four tools, the autonomous stance, and the
`provisional` flag). The active block is empty (`no active decisions`).
Nothing else tells the agent EDP exists. The agent has never been told
"use `edp_record`" in any user message.

---

## Session 1 — design phase (empty store → 4 decisions)

**User asked for:** the design of a tiny in-memory LRU+TTL cache library
with a `@cached` decorator. No mention of EDP.

The agent had a normal design conversation, made picks, and at the
points where it was committing to something architecturally non-trivial,
it autonomously called `edp_record`.

| ID | Title | Confidence | `revision_conditions` |
|---|---|---|---|
| DEC-0001 | Cache miss is an exception (`CacheMiss`), not a None sentinel | 0.9 | — |
| DEC-0002 | v0 scope: in-memory, single-threaded, LRU+TTL only | 0.8 | thread-safety / async / persistence / pluggable eviction requested |
| DEC-0003 | Explicit-policy API: `max_size` and `ttl` always required, no implicit defaults | 0.9 | — |
| DEC-0004 | TTL math uses `time.monotonic()`, not `time.time()` | 0.95 | persistence or cross-process state is added |

Two things in this table are load-bearing.

**The agent cited the user's *global* `CLAUDE.md` as evidence on DEC-0001
and DEC-0003.** Verbatim from `.edp/decisions/DEC-0001.md`:

> Evidence: `user global CLAUDE.md: 'Always raise errors explicitly, never silently ignore them'`

The per-project `CLAUDE.md` was empty. The agent reached for the user's
global rules file as evidence because the primer told it decisions need
evidence and that was the most relevant artifact in scope. Nothing in EDP
told it where to look for evidence — it figured out the available sources
on its own.

**The agent populated `revision_conditions` on DEC-0002 and DEC-0004
without being asked to.** It correctly distinguished cases where the
decision is permanent (DEC-0001, DEC-0003) from cases where a future
event should re-open the discussion (scope expansion, persistence). This
field is brand new in v0.1.1 — the agent learned about it from the
primer and used it correctly on the first call.

Session 1 ended. No human edits were made to the store. The `.edp/`
directory was carried forward verbatim to session 2.

---

## Session 2 — implementation phase (different topic, decisions still respected)

**User asked for:** "two teams need this — one wants to call `Cache` from
multiple worker threads, the other wants to swap the backend for Redis
later. What do we change?" No EDP mention.

This is the interesting test. The session-1 decisions were no longer in
the user's prompt, no longer in the conversation history of session 2,
and no longer in any `CLAUDE.md`. They existed **only** in the
`<edp:active>` block injected by the `UserPromptSubmit` hook on each
turn.

The agent took two actions, both citing session-1 commitments:

### Action 1 — formal supersede with reasoning chain

```
edp_supersede(
  old_id="DEC-0002",
  title="v0→v1 scope: thread-safe via single Lock; Redis and async still deferred",
  decision="Cache uses a single threading.Lock to protect all mutations...",
  key_constraints=[
    "threading.Lock is the only concurrency primitive — no RWLock, no asyncio",
    "Redis backend is explicitly deferred (cross-process monotonic clock breaks DEC-0004; needs serialization design)",
    ...
  ],
  revision_conditions=[
    "read-heavy profiling shows lock contention > 5% of latency — revisit RWLock or lock striping",
    "Redis backend design session begins"
  ],
  evidence=[
    "session_2/user_request: multiple worker threads hitting cache; single writer + many readers is realistic load",
    "DEC-0004 constraint: monotonic expires_at is not safe to serialize across processes, blocking naive Redis port"
  ]
)
→ DEC-0005
```

Note the second evidence line. The agent is citing the technical
constraint from a session-1 decision (`DEC-0004`'s monotonic-clock
choice) as a reason for a session-2 design move. The supersede chain
`DEC-0002 → DEC-0005` is preserved. The previous decision is not
deleted.

### Action 2 — feature deferral by causal link

The Redis request is a separate concern — not a supersede of any prior
decision, but a new commitment to *not* ship something. The agent
recorded it as `DEC-0006`:

```
edp_record(
  title="Redis backend deferred: needs serialization + clock design before v1",
  decision="A Redis backend is not shipped in this session. Blockers: (1) DEC-0004 — expires_at is a monotonic value, meaningless when deserialized in another process; (2) Serialization — Cache[K,V] is generic over arbitrary Python objects; a Redis store needs an explicit codec. (3) API semantics — network errors, connection pools, and serialization failures are a different error surface than in-memory misses.",
  key_constraints=[
    "do not add a redis optional dep to this package without a full design",
    "a Redis adapter must not reuse the monotonic expires_at field — it needs wall-clock TTL passed to Redis EXPIRE",
    "RedisCache should be a separate class, not a Cache subclass or backend flag"
  ],
  evidence=[
    "session_2/user_request: one team wants Redis for cross-process sharing",
    "DEC-0004: monotonic deadlines not safe to serialize across processes"
  ]
)
→ DEC-0006
```

This is the cross-session causal link in code. `DEC-0004`'s
`revision_conditions` listed *"persistence or cross-process state is
added"* in session 1. In session 2 the agent recognised that the Redis
request triggers exactly that condition — and instead of silently
implementing Redis, it recorded the deferral with `DEC-0004` cited
explicitly as the technical reason.

A human reviewer running `edp events --decision DEC-0006` weeks later
can reconstruct why the v0 Redis backend doesn't exist without asking
anyone — the chain from `DEC-0004`'s `revision_conditions` to the
`DEC-0006` deferral is in the append-only events log.

---

## Final store after both sessions

```
DEC-0001 [active]      conf=0.9   Cache miss is an exception (CacheMiss), not a None sentinel
DEC-0002 [superseded]  conf=0.8   v0 scope: in-memory, single-threaded, LRU+TTL only        → DEC-0005
DEC-0003 [active]      conf=0.9   Explicit-policy API: max_size and ttl always required
DEC-0004 [active]      conf=0.95  TTL math uses time.monotonic(), not time.time()
DEC-0005 [active]      conf=0.9   v0→v1 scope: thread-safe via single Lock; Redis and async still deferred
DEC-0006 [active]      conf=0.92  Redis backend deferred: needs serialization + clock design before v1
```

5 active decisions, 1 supersede chain (`DEC-0002 → DEC-0005`),
1 explicit cross-session causal-link write (`DEC-0006` citing
`DEC-0004`). All recorded by the agent. No human edits.

---

## What this trial does and does not prove

**Does prove (N=1, single model, single project, single user):**

- An agent given only the primer (no per-project `CLAUDE.md`, no leading
  prompt) can spontaneously adopt the `edp_record` workflow during
  normal design conversation. Threshold for "spontaneous" is ≥1
  unprompted record — observed: 4.
- The agent correctly uses the v0.1.1 `revision_conditions` field on
  decisions where it makes sense (scope, time-sensitivity), and leaves
  it empty where it does not. No false positives in this trial.
- A decision made in session 1 can shape an action in session 2 via a
  formal causal link — the `revision_conditions` field of `DEC-0004` is
  the mechanism, and `DEC-0006`'s evidence list is the audit trail.
- The supersede primitive is used the way the spec intends: a new
  decision replaces an old one and the old one is marked superseded,
  not deleted. The audit log preserves the reasoning.

**Does not prove:**

- That every model in every harness will do this. Different models have
  different biases about tool use. The primer + the `provisional=False`
  default are intentional nudges but they are not magic.
- That the agent always remembers to consult. The companion test
  `tests/integration/langgraph_naturalistic.py` on `gpt-4.1-mini` shows
  one honest failure mode: when an implementation request follows
  immediately after a design session, the agent worked from the
  snippet visible in its context and never called `edp_check` or
  `edp_show`. Snippet-first reasoning is intended behavior (it's why
  snippets exist), but the test scorecard flagged it as a missed
  consult. We report this as 2/3 PASS, not 3/3 — the spec does not
  promise tool calls when snippets suffice.
- That the protocol scales to hundreds of decisions in a single store
  without selector tuning. The selector has a `token_budget` knob and a
  trim policy; that path is unit-tested, not yet long-horizon-tested.

For statistically meaningful claims, the SPEC §11 Sprint-7 design
(paired k=4 runs × 20–30 tasks, EDP-on vs EDP-off, mid-tier model) is
the gating experiment. This file is the calibration that motivates
running it.

---

## Reproducing this trial

The raw `tinycache` project artifacts are local-only and not committed
to this repo (they are throwaway code written by the agent during the
trial). The decision bodies above are the load-bearing evidence, and
they are reproducible. To run your own trial:

1. Install EDP per `README.md` Quick install.
2. Create the empty project as in the **Setup** section above.
3. Install the standalone Claude Code adapter
   (`adapters/claude-code-plugin/standalone/`).
4. Open a Claude Code session in `/tmp/edp-blank/`.
5. Ask the agent to design a small library (anything will do — pick a
   problem domain you know). Do **not** mention EDP, do **not** mention
   `edp_record`, do **not** put anything in `CLAUDE.md`.
6. End the session. Open a second session a day later. Ask for a
   feature that pressures one of the recorded decisions.

Expected behavior: at least one `edp_record` call in session 1, and at
least one of `edp_supersede` / `edp_check` / `edp_show` in session 2.
If you get zero — open a GitHub issue with the trace. That is the
failure mode we most want to learn from.

---

## Companion: naturalistic test on a smaller model

The same shape of test, but automated and against a cheaper model (no
human-in-the-loop), lives at
`tests/integration/langgraph_naturalistic.py`. It runs three turns
against `gpt-4.1-mini` via OpenRouter using the LangGraph binding and
the primer-via-`inject_into_messages` path. Scorecard from the most
recent run (2026-05-25) — reproduce by running the script with
`OPENROUTER_API_KEY` set:

| Turn | What is measured | Result |
|---|---|---|
| 1 | ≥2 spontaneous `edp_record` calls on empty store during design | PASS (4 records) |
| 2 | ≥1 `edp_check`/`edp_show` consult on follow-up implementation | FAIL (0 — agent worked from snippet alone) |
| 3 | Conflict request → must supersede or cite, not silently comply | PASS (2 supersedes) |

**Turn 2 is reported honestly as a failure.** The agent's behavior
(reading the snippet in context and acting on it) is not actually wrong
— that is what snippets are *for*. The test criterion is stricter than
the spec intent. We choose to publish the strict criterion and the
failure rather than loosen it; loosening the bar to make our own test
pass would be exactly the kind of self-serving evaluation move EDP
exists to prevent.

The Opus 4.7 session above used the same primer path. We have not run
the strict naturalistic harness against Opus 4.7 because it requires UI
approval for every MCP tool call and is not automatable.
