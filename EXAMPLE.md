# EDP in action — example session

This walkthrough is a verbatim trace from the `tinycache` blank-slate
trial documented in [`docs/dogfood-tinycache.md`](docs/dogfood-tinycache.md).
A coding agent (Opus 4.7 via Claude Code, standalone hooks adapter) was
asked to design a tiny in-memory cache library across two sessions.
**The project's `CLAUDE.md` was empty (`0 bytes`), the store was empty,
and no user prompt mentioned EDP.** The only EDP signal was the
~280-token protocol primer injected once by the `SessionStart` hook.

Everything below — the decisions, the supersede, the cross-session
causal link — was written by the agent without being instructed to use
EDP at any point.

---

## Session 1 — session start

The `SessionStart` hook fires. The agent sees this at the top of its
first turn (showing the relevant excerpt; the active block is empty
because the store is empty):

```
<edp:protocol>
You have access to EDP — Explicit Decision Protocol. Four tools:
  edp_record(...)     create a new decision
  edp_show(id)        full body of one decision
  edp_check(action)   relevant decisions for a planned action
  edp_supersede(...)  formally replace a decision
…autonomous stance: you are committing decisions, not proposing them…
</edp:protocol>

<edp:active version="1">
(no active decisions yet — call edp_record when you commit to one)
</edp:active>
```

User prompt: *"Help me design a tiny in-memory cache library — Cache[K,V] with LRU eviction, TTL, and a @cached decorator."*

---

## Session 1 — agent commits to its first decision

The conversation moves through API shape. The agent picks an exception
rather than a sentinel for misses. That is an architectural commitment,
not a stylistic choice, and the primer told it to record commitments.

```
edp_record(
  title="Cache miss is an exception (CacheMiss), not a None sentinel",
  decision="Cache.get raises CacheMiss (a KeyError subclass) when a key is absent or expired. It never returns None on miss. Rationale: distinguishes 'absent' from 'present with value None' cleanly; consistent with dict[k] semantics; aligned with the user's 'raise errors explicitly, never silently ignore them' rule. KeyError inheritance keeps existing `except KeyError` handlers working while letting callers be specific with `except CacheMiss`.",
  key_constraints=[
    "Cache.get must raise on miss, never return a sentinel",
    "CacheMiss must remain a KeyError subclass for backwards compatibility",
    "any future get_or_compute / try_get helpers must layer on top of get + try/except, not replace the raising semantic"
  ],
  evidence=[
    "src/tinycache/core.py:CacheMiss",
    "src/tinycache/core.py:Cache.get",
    "user global CLAUDE.md: 'Always raise errors explicitly, never silently ignore them'"
  ],
  confidence=0.9
)
→ "DEC-0001"
```

Note the third evidence line. The per-project `CLAUDE.md` was empty —
the agent reached for the user's **global** rules file as evidence
because it was the most relevant artifact in scope. Nothing in EDP told
it where to look for evidence.

---

## Session 1 — recording with `revision_conditions`

A few turns later the agent commits to the v0 scope (no threading, no
async, no persistence). This is a decision that *should* be re-opened
under specific future conditions — and v0.1.1's `revision_conditions`
field is exactly for that:

```
edp_record(
  title="v0 scope: in-memory, single-threaded, LRU+TTL only",
  decision="tinycache v0 is intentionally narrow…",
  key_constraints=[
    "no threading.Lock or asyncio primitives in core.py at v0",
    "no policy plugin/strategy interface yet",
    "if a future session wants to add thread-safety, the lock granularity (per-cache vs per-entry vs lock-free) is itself an EDP-worthy decision"
  ],
  revision_conditions=[
    "user requests thread-safety, async support, persistence, or pluggable eviction policies",
    "real usage surfaces a need that LRU+TTL cannot serve"
  ],
  evidence=["src/tinycache/core.py — no concurrency primitives"],
  confidence=0.8
)
→ "DEC-0002"
```

And one more — the clock-choice decision, which is permanent for the
in-memory case but breaks if anyone later tries to serialize state:

```
edp_record(
  title="TTL math uses time.monotonic(), not time.time()",
  decision="All expiration arithmetic uses time.monotonic(). Never time.time() / datetime.now(). Wall-clock jumps (NTP adjustments, DST, manual clock changes) must not cause spurious early expiry or indefinite hangs. _Entry.expires_at stores a monotonic deadline. Note: monotonic clocks are process-local — if persistence/cross-process state is added later, that boundary will need an explicit conversion or a different model.",
  key_constraints=[
    "never read time.time() or datetime.now() for TTL math",
    "expires_at is always a monotonic value, never wall-clock",
    "monotonic deadlines are not safe to serialize across processes"
  ],
  revision_conditions=["persistence or cross-process state is added"],
  evidence=[
    "src/tinycache/core.py:_is_expired",
    "src/tinycache/core.py:Cache.set uses monotonic() + ttl"
  ],
  confidence=0.95
)
→ "DEC-0004"
```

This `revision_conditions` entry is the key to what happens in session 2.

By end of session 1, four decisions are recorded: API surface, scope,
explicit-policy rule, clock choice. The session closes. The store on
disk is the only continuity between sessions.

---

## Session 2 — different topic, same store, one day later

A new Claude Code session opens. `SessionStart` hook fires. The agent
sees the primer again plus this active block (showing snippet excerpts):

```
<edp:active version="1">
DEC-0001 [active] conf=0.9
  Title: Cache miss is an exception (CacheMiss), not a None sentinel
  Key constraints: Cache.get must raise on miss · CacheMiss must remain KeyError subclass · ...
DEC-0002 [active] conf=0.8 triggers:2
  Title: v0 scope: in-memory, single-threaded, LRU+TTL only
  Key constraints: no threading.Lock or asyncio primitives · no policy plugin interface · ...
DEC-0003 [active] conf=0.9
  Title: Explicit-policy API: max_size and ttl always required, no implicit defaults
  Key constraints: all public APIs require max_size and ttl explicitly · ...
DEC-0004 [active] conf=0.95 triggers:1
  Title: TTL math uses time.monotonic(), not time.time()
  Key constraints: never read time.time() or datetime.now() for TTL math · ...

Active: 4 · `edp.show(id)` for full body · `edp.check(action)` before risky moves · `edp.record(...)` to commit new ones · use only version="1"
</edp:active>
```

User prompt: *"Two teams need this — one wants to call Cache from multiple worker threads, the other wants to swap the backend for Redis later. What do we change?"*

The user does not mention EDP, does not reference any DEC id, does not
re-paste the session-1 decisions. The decisions exist only in the
snippet block above.

---

## Session 2 — formal supersede with reasoning chain

The agent recognises that the thread-safety request directly conflicts
with `DEC-0002`'s "no concurrency primitives" constraint. This is not a
bug fix or an edit — it is a scope change that the spec calls a
**supersede**:

```
edp_supersede(
  old_id="DEC-0002",
  title="v0→v1 scope: thread-safe via single Lock; Redis and async still deferred",
  decision="Cache uses a single threading.Lock to protect all mutations and reads of _store and stat counters. This covers the 'single writer + many readers' production load at correctness cost (readers block on write lock). No asyncio primitives. No persistence API. No plugin/strategy interface.",
  key_constraints=[
    "threading.Lock is the only concurrency primitive — no RWLock, no asyncio",
    "Redis backend is explicitly deferred (cross-process monotonic clock breaks DEC-0004; needs serialization design)",
    "no policy plugin/strategy interface yet",
    "no sync persistence API"
  ],
  revision_conditions=[
    "read-heavy profiling shows lock contention > 5% of latency — revisit RWLock or lock striping",
    "Redis backend design session begins"
  ],
  evidence=[
    "session_2/user_request: multiple worker threads hitting cache; single writer + many readers is realistic load",
    "DEC-0004 constraint: monotonic expires_at is not safe to serialize across processes, blocking naive Redis port"
  ],
  confidence=0.9
)
→ "DEC-0005"
```

Two things to notice. First, the new `revision_conditions` list pre-records
what would *next* re-open this — lock contention or a Redis design
session. The supersede chain `DEC-0002 → DEC-0005` is preserved in the
store; the old decision is marked `superseded`, not deleted.

Second, the second evidence line is a **cross-decision citation**: the
agent is referencing the technical constraint baked into `DEC-0004`
(monotonic clock) as a reason for the session-2 design move. It did not
have to call `edp_show("DEC-0004")` to get this — the constraint was
visible in the snippet block.

---

## Session 2 — cross-session causal link

The Redis request is a separate concern — not a supersede of any prior
decision, but a new commitment to *not* ship something for a specific
technical reason. The agent records it:

```
edp_record(
  title="Redis backend deferred: needs serialization + clock design before v1",
  decision="A Redis backend is not shipped in this session. The blockers are: (1) DEC-0004 — expires_at is a monotonic value, meaningless when deserialized in another process; a Redis port requires a wall-clock-based expiry strategy or a separate TTL field that Redis manages natively. (2) Serialization — Cache[K,V] is generic over arbitrary Python objects; a Redis store needs an explicit codec. (3) API semantics — network errors, connection pools, and serialization failures are a different error surface than in-memory misses. A Redis backend should be a separate class, not a flag on Cache.",
  key_constraints=[
    "do not add a redis optional dep to this package without a full design",
    "a Redis adapter must not reuse the monotonic expires_at field — it needs wall-clock TTL passed to Redis EXPIRE",
    "RedisCache should be a separate class, not a Cache subclass or backend flag"
  ],
  evidence=[
    "session_2/user_request: one team wants Redis for cross-process sharing",
    "DEC-0004: monotonic deadlines not safe to serialize across processes"
  ],
  confidence=0.92
)
→ "DEC-0006"
```

This is the cross-session causal link in code. `DEC-0004`'s
`revision_conditions` had listed *"persistence or cross-process state
is added"* back in session 1. In session 2 the agent recognised that
the Redis request triggers exactly that condition, and instead of
silently implementing Redis it recorded a formal deferral citing
`DEC-0004` as the technical reason.

A human reviewer reading `.edp/events/` weeks later can reconstruct
**why** the v0 Redis backend doesn't exist without asking anyone.

---

## Final store state

```
DEC-0001 [active]      conf=0.9   Cache miss is an exception (CacheMiss), not a None sentinel
DEC-0002 [superseded]  conf=0.8   v0 scope: in-memory, single-threaded, LRU+TTL only        → DEC-0005
DEC-0003 [active]      conf=0.9   Explicit-policy API: max_size and ttl always required
DEC-0004 [active]      conf=0.95  TTL math uses time.monotonic(), not time.time()
DEC-0005 [active]      conf=0.9   v0→v1 scope: thread-safe via single Lock; Redis and async still deferred
DEC-0006 [active]      conf=0.92  Redis backend deferred: needs serialization + clock design before v1
```

5 active, 1 supersede chain, 1 cross-session causal-link write. All
written by the agent. No human edits.

---

## What is and is not happening here

**Is happening:**
- Decisions are persistent and visible on every turn via the snippet block.
- The agent can supersede a prior decision when scope changes, preserving the chain.
- `revision_conditions` records the events that should re-open a decision later — and the agent uses it to make causal links across sessions.
- The agent recognises when a user request triggers a previously-recorded `revision_conditions` entry and acts accordingly (defer + cite, not silently comply).
- The agent reaches for the most relevant evidence sources in scope (including the user's global `CLAUDE.md`) without being told where to look.

**Is not happening:**
- No proxy is intercepting tool calls or blocking actions. The agent is in charge.
- No semantic search, no embeddings. The selector is lexical/recency-based per SPEC §4.3.
- No human is editing the store between sessions. All writes are the agent's.
- The agent did not always call `edp_check` before implementing — when the snippet block already showed the relevant constraints, it acted on those directly. The companion `tests/integration/langgraph_naturalistic.py` flags this as a turn-2 FAIL on `gpt-4.1-mini`; we report it honestly rather than relax the criterion.

The agent is in charge of its own work. EDP just makes its own past
decisions hard to forget.
