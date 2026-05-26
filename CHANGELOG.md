# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Specification versions are date-stamped (`edp/YYYY-MM-DD`), not semver. SDK versions follow semver and declare which spec version(s) they implement.

## [Unreleased]

## [0.3.0] — 2026-05-26

The "constraints primitive" release. v0.3 introduces a second first-class
primitive alongside `Decision`: a non-negotiable **`Constraint`** (axiom).

Rationale (from the source `decision-protocol-template.md` reread plus
operator feedback): conflating axioms with decisions is a categorical
error. A risk limit like "max leverage 10x" has no revision conditions,
no alternatives considered, no rationale to preserve when it changes —
modifying it is a remove-then-add operation, not a supersede chain. EDP
v0.1/v0.2 wedged these into `Decision.key_constraints` strings, which
the verifier read but treated as ordinary invariants. v0.3 separates the
two so the verifier can apply the right severity, and so the active
block can pin constraints at the top, never trimmed for token budget.

### Added

- **`Constraint` model** (`edp.models.Constraint`) — id (CON-NNNN), rule
  (≤200 chars), `created_at_ts`, `created_by`, `tags`, `provisional`.
  Intentionally minimal: no status, no supersede chain, no
  revision_conditions, no confidence. Axioms are absolute or they are
  not axioms.
- **SQLite `constraints_current` table** + `last_constraint_id` counter.
  Schema bumped to v2. Migration is forward-only and idempotent
  (CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE counter row) — existing
  v0.2 stores upgrade transparently on first open.
- **Store CRUD**: `DecisionStore.add_constraint`, `list_constraints`,
  `show_constraint`, `remove_constraint`, `confirm_constraint`. Append-
  only event log records `con_add` / `con_remove` / `con_confirm` ops.
- **CLI**: `edp constraint add|list|show|remove|confirm`.
- **MCP tools**:
  - `edp_constraints()` — read, always exposed
  - `edp_add_constraint(rule, tags=...)` — mode-gated by
    `EDP_CONSTRAINT_MODE` env var:
    - `human_only` (default) — agent CANNOT create constraints; tool
      is hidden from the MCP surface entirely. Operator-only via CLI.
    - `agent_auto` — agent creates directly.
    - `agent_provisional` — agent creates `provisional=True`; operator
      confirms via `edp constraint confirm CON-NNNN`.
- **Active-block constraints section** — rendered at the top of
  `<edp:active>`, before decisions, **never trimmed** for token budget.
  Header: "Constraints (non-negotiable axioms — violation must be
  refused)". Footer line gains `Constraints: N` count.
- **Verifier integration** — `verify(planned_action, active_decisions,
  active_constraints=...)`. Constraints render in a dedicated
  `ACTIVE CONSTRAINTS` section of the prompt; the system prompt
  instructs the verifier model to treat constraint violations as
  strictly more severe than invariant violations. The PreToolUse hook
  passes both lists to the verifier; on `violated` against a CON-* id
  the block-reason message explicitly notes that constraints CANNOT be
  superseded by the agent and must be escalated to the operator.
- **`render_constraint_snippet` + `render_constraint_markdown`** — and
  hybrid storage: source of truth is SQLite, with auto-projected
  `.edp/constraints/CON-NNNN.md` for human/git diff readability (same
  pattern as decisions).
- **`/edp-constraints` slash command** for Claude Code.
- **PROTOCOL_PRIMER updated** — distinguishes the two primitives
  (CONSTRAINTS vs DECISIONS), documents `edp_constraints` and the
  no-supersede semantic for axioms.
- **30 new unit tests** in `test_constraints.py` covering model
  validation, CRUD round-trip, event log, markdown projection,
  never-trimmed-in-active-block, MCP mode-gating, verifier prompt
  shape.

### Changed

- **`_SDK_SCHEMA_VERSION` → 2.** Old v0.2 stores migrate forward on
  first open; no data migration required (new table + counter only).
- **`wrap_active_block` signature** — gains `constraint_snippets` +
  `total_constraints` keyword args (defaults preserve v0.2 behaviour).
  Footer count line now reads `Constraints: N · Active decisions: M`
  when at least one constraint exists (was `Active: M`).
- **`verifier_hook` runs when either invariants OR constraints exist.**
  v0.2 short-circuited to allow when no decision had invariants; v0.3
  also runs if any constraint is active.

### Why this is not a major bump

Backwards-compatible at the API level:
- All v0.2 tools (`edp_record`, `edp_check`, `edp_verify`, `edp_show`,
  `edp_supersede`) preserve their signatures and behaviour.
- The `Decision` model is unchanged.
- Old stores upgrade silently via additive-only schema migration.
- New behaviour is opt-in: with zero constraints, the active block and
  verifier output look identical to v0.2.

## [0.2.0] — 2026-05-25

The "source-doc alignment" release. v0.2 closes the philosophical gap
the 4-agent audit caught: the original source `decision-protocol-template.md`
defines `invariants` + a pre-action verifier as the load-bearing mechanism
that makes decision drift recoverable. v0.1 deliberately ran the
visibility-only experiment; v0.2 adds the verifier-gate path back, on top
of v0.1's visibility primitive, so implementations have BOTH mechanisms
available and can choose per use case.

### Added

- **`invariants: list[str]` field on `Decision`** — machine-checkable
  predicates the verifier enforces. ≤200 chars each. Distinct from
  `key_constraints` (which remain the human-facing summary surfaced
  in the snippet block). Round-trips through `store.record`,
  `store.supersede`, the MCP `edp_record` / `edp_supersede` tools,
  and the markdown projection.
- **`edp.verifier` module** — `verify(planned_action, active_decisions)`
  → `CompatibilityReport(verdict, reasoning, violated_decision_ids)`.
  Calls a Haiku-class model via the Anthropic SDK with structured
  tool_use; defaults to `claude-haiku-4-5-20251001` (overridable via
  `EDP_VERIFIER_MODEL`). Optional dependency: install with
  `pip install 'explicit-decision-protocol[verifier]'`.
- **`edp_verify(planned_action)` MCP tool** — HARD pre-action check
  exposed to the agent, alongside the existing SOFT `edp_check`. Returns
  `CompatibilityReport`. Falls through to `verdict="uncertain"` with
  reasoning when the verifier dependency is unavailable, so the agent
  always gets a meaningful response.
- **`edp.verifier_hook` module** — Claude Code `PreToolUse` hook
  implementation. Reads the planned tool call, runs the verifier
  against active decisions' invariants, returns `permissionDecision:
  "deny"` with citation reasoning on `violated`. Fails OPEN by default
  (never breaks the user's session because of missing verifier infra);
  set `EDP_VERIFIER_REQUIRED=1` to fail closed.
- **`edp claude-code install --enable-verifier`** — installs the
  `PreToolUse` hook on write-class tools (Edit | Write | Bash |
  str_replace_editor). The matcher targets only state-mutating tools
  per the source `decision-framework-reliability.md` §7 ("Cheap checks
  везде, expensive в Pareto 20% high-risk actions"). Opt-in for v0.2;
  on-by-default tentatively scheduled for v0.3 once the visibility-vs-
  gating effect is measured by the benchmark.
- **Snippet markers `inv:N`, `alts:N`, `risks:N`** — `render_snippet`
  surfaces previously-dropped fields in the attention-sink so the agent
  knows what to fetch via `edp_show` before acting. `alts:N` and
  `risks:N` close the gap D's audit named: rejected alternatives and
  consequences were already in the data model but invisible at the
  per-turn snippet.
- **`## Invariants` section in full-body markdown projection** — with a
  human-facing explanation of the assertable-predicate contract.
- **19 new unit tests** in `test_invariants_and_verifier.py` covering
  invariants round-trip, supersede-chain invariant preservation, length
  validation, snippet markers, primer + footer updates, verifier_hook
  fail-open vs fail-closed, install/uninstall with `--enable-verifier`.

### Changed

- **`PROTOCOL_PRIMER` updated to describe FIVE tools** (added
  `edp_verify`) plus the four snippet markers (`inv:N`, `alts:N`,
  `risks:N`, `triggers:N`). Token count ~360 (up from ~280).
- **Active-block footer mentions `edp.verify(action)`** as HARD
  pre-action check alongside the SOFT `edp.check(action)` advisory.
- **`SPEC.md §3.6` rewritten** (already shipped in v0.1.4 commit
  `69c831f`) — steelman of the visibility-only thesis + sketch of the
  v0.2 verifier extension point that this release implements.

### Why now

Two independent audits (`.planning/research/source-vs-current-diff.md`
and `.planning/research/anthropic-grade-audit-2026-05-25.md`)
converged on the same gap: v0.1's `key_constraints + edp_check` is at
the wrong level of the user's own reliability hierarchy (visibility ≈
Level 0; the source mapped decision drift to Level 3 = programmatic
invariants + pre-action verifier). Empirical confirmation in our own
data: the naturalistic test Turn 2 FAIL (`consults_count: 0`) shows
visibility-alone did not prevent silent drift on `gpt-4.1-mini`. v0.2
ships the gating mechanism the source design called for, opt-in, so
the upcoming benchmark can quantify the marginal effect of gating-on-
top-of-visibility vs visibility-alone.

### Not in this release (deferred to v0.2.1 / v0.3)

- `edp_due` + `edp_review` MCP tools — D's audit flagged
  `store.due()` and `review_history` as half-wired dead branches; the
  storage layer is ready but no MCP tool exposes them, no hook fires
  on subtask boundary. Wiring deferred to v0.2.1 (~2-3 days).
- Verifier `on-by-default` — kept opt-in for v0.2 so the benchmark can
  cleanly A/B test gating vs no-gating without a measurement
  confounder. v0.3 will flip the default based on benchmark results.
- Conformance test suite + TypeScript SDK — audit `CRIT-1` and `CRIT-3`
  from the MCP-co-author audit. Tracked for v0.3.

## [0.1.3] — 2026-05-25

### Added

- **`edp claude-code install` CLI subcommand** — installs the EDP hook +
  MCP server registration + six `/edp-*` slash commands into a project's
  `.claude/` directory in a single command. Auto-creates `.edp/` if
  missing, uses `sys.executable` so the generated `settings.json` points
  at the right Python interpreter without manual path editing, merges
  with existing `.claude/settings.json` instead of overwriting, and is
  idempotent on re-run (flags: `--force` to overwrite EDP entries,
  `--no-init` to skip the auto `edp init`, `--target` to point at a
  non-default `.claude/`).
- **`edp claude-code uninstall` CLI subcommand** — symmetric removal:
  strips EDP hook entries from `settings.json`, removes the `edp` MCP
  server entry, deletes `/edp-*` slash commands. Leaves user-owned
  hooks/MCP servers/slash commands intact. **Does not** delete `.edp/`
  — your decisions are preserved.
- **`edp.hook` module** — the Claude Code hook is now an importable
  package module invokable via `python -m edp.hook SessionStart`. This
  removes the need to reference an absolute filesystem path in
  `.claude/settings.json` (workaround for the still-open
  [claude-code#4276 / #46889](https://github.com/anthropics/claude-code/issues/46889)
  env-var-substitution gap).
- **Slash commands packaged as `edp/commands/*.md`** — the six
  `/edp-record`, `/edp-show`, `/edp-check`, `/edp-supersede`,
  `/edp-list`, `/edp-events` markdown files ship inside the wheel and
  are copied to `.claude/commands/` by `edp claude-code install` via
  `importlib.resources`.
- 12 new unit tests in `sdk-python/tests/test_claude_code_install.py`
  covering fresh install, settings format, MCP entry shape, idempotency,
  merge-with-unrelated-hooks, `--no-init`, `--force` overwrite, invalid
  JSON refusal, uninstall surgical removal, uninstall preserves the
  store, and uninstall on a clean project being a no-op.

### Changed

- `adapters/claude-code-plugin/standalone/hooks/edp_hook.py` is now a
  thin back-compat shim that delegates to `edp.hook.main()`. Existing
  `.claude/settings.json` files that reference its absolute path keep
  working.
- README.md "Claude Code in 60 seconds" → **"Claude Code in 2 commands"**
  with the new install command flow.
- `adapters/claude-code-plugin/README.md` reorganised: the
  `edp claude-code install` path is now primary; the previous "drop the
  four files into `.claude/`" workflow is preserved as a "Manual install
  (long form)" section for users who cannot install Python packages
  globally.
- `sdk-python/README.md` Claude Code section rewritten around the new
  2-command flow.

### Why

Friction points caught when documenting the install UX: the previous
flow required (1) `git clone` for adapter files, (2) editing an absolute
path in `settings.json`, (3) waiting on plugin-form distribution that is
blocked upstream on the still-broken
[claude-code#16538](https://github.com/anthropics/claude-code/issues/16538)
(closed by bot in May 2026 for inactivity but never actually fixed).
v0.1.3 eliminates all three.

## [0.1.2] — 2026-05-25

### Added

- **Protocol primer auto-injected on `SessionStart`** — the standalone
  Claude Code hook now passes `--primer` on `SessionStart` events so an
  agent that has never used EDP discovers the four tools and the
  autonomous stance without any per-project `CLAUDE.md` content. Per-turn
  `UserPromptSubmit` injections omit the primer (token-cost economy).
- `tests/integration/langgraph_naturalistic.py` — naturalistic adoption
  test with strict pass criteria. No leading prompts; uses primer only.
  Result on `gpt-4.1-mini`: 2/3 PASS (Turn 2 FAILS by design — agent
  works from snippet alone, which is the intended snippet-first
  behaviour). Honest measurement, not "leading the witness".
- `wrap_active_block(include_primer=...)` and
  `inject_into_messages(primer=...)` parameters in the SDK.
- Empty-store placeholder in the active block now mentions `edp_record`
  to guide first-time agents.

### Fixed

- `edp_before_model` rewritten as an `AgentMiddleware` subclass for
  LangChain v1.1+ compatibility (the prior `@before_model`-decorator
  form broke after the v1.1 API change).
- Selector test assertion updated for the new empty-store hint.

## [0.1.1] — 2026-05-24

### Added

- **`revision_conditions: list[str]` field on `Decision`** — event-based
  re-examination triggers (natural-language), distinct from
  `review_due_at_step` which is step-based. Rendered as `triggers:N`
  marker in snippets and as a `## Revision conditions` section in full
  markdown bodies.
- `revision_conditions` parameter on `store.record(...)` and
  `store.supersede(...)` (and through to the LangGraph binding's
  `edp_record` / `edp_supersede` tools).

### Changed

- **`provisional: bool` default flipped from `True` to `False`.**
  Most agent-recorded decisions are commitments, not proposals — the
  prior default forced unnecessary agent reasoning about whether to
  set the flag every call. Set `provisional=True` explicitly only when
  confidence is low *and* supersede is not the right move.
- All MCP tool annotations audited per spec 2025-06-18 — reads marked
  `readOnlyHint=true, idempotentHint=true`; `edp_record` marked
  `destructiveHint=false`; `edp_supersede` marked `destructiveHint=true`.
  Defaults are no longer relied upon (spec calls them "destructive").
- Markdown projection now regenerated on agent writes inside
  `store.record` / `store.supersede` (previously only the CLI path
  refreshed projections).

### Fixed

- Selector no longer silently swallows broken supersede chains. Raises
  a narrow `DecisionNotFound` with structured-log context instead.

## [0.1.0] — 2026-05-24

### Added

- v0.1 specification draft (`SPEC.md`, spec version `edp/2026-05-24`),
  tag `v0.1.0-spec`.
- JSON Schema for the Decision record (`spec/v0.1/schema.json`).
- Example walkthrough of an agent session using EDP (`EXAMPLE.md` —
  initially synthetic; replaced with real trace in unreleased).
- Python SDK implementation (`sdk-python/`) — models, store, selector,
  render, server (FastMCP), CLI, LangGraph binding. Unit-tested.
- Claude Code adapter, standalone hooks form
  (`adapters/claude-code-plugin/standalone/`) — `SessionStart` +
  `UserPromptSubmit` hooks, MCP-server registration, 6 slash commands.
- MCP server adapter (`adapters/mcp-server/`) — install matrix for
  Claude Desktop, Claude Code, Cursor, Cline, Continue. `smoke.py`
  exercises the protocol probes.
- LangGraph middleware adapter
  (`adapters/middleware-langgraph/`) — two injection modes
  (helper-style `inject_into_messages` and class-based `AgentMiddleware`)
  with two runnable examples.
- Sample project layout under `examples/sample-project/`.
- Evidence pass — `docs/evidence.md` with 22 third-party citations.

### Notes

- Initial public draft. Breaking changes to the spec expected before v1.0.
