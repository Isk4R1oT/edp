# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Specification versions are date-stamped (`edp/YYYY-MM-DD`), not semver. SDK versions follow semver and declare which spec version(s) they implement.

## [Unreleased]

### Added

- `docs/dogfood-tinycache.md` — public sanitized trace of a two-session
  blank-slate trial on Opus 4.7. Cited from `README.md` and
  `docs/evidence.md` (new §5 "Own dogfood findings").
- `README.md` — new "Does it actually work?" section between the snippet
  block and "Why a protocol, not a library". Distinguishes first-party
  dogfood findings from third-party citations.
- `docs/evidence.md` — new §5 "Own dogfood findings" with three buckets
  (blank-slate trial, naturalistic test, explicit integration test) and
  an explicit list of what has NOT yet been measured.
- `EXAMPLE.md` — now a walkthrough of the real tinycache dogfood trial
  (decision bodies verbatim from the store; snippet blocks rendered
  illustratively) rather than a synthetic enterprise example.

### Changed

- `README.md` Status & roadmap — refreshed test counts (48 unit tests,
  9 hook tests including primer auto-inject) and added v0.1.1 / v0.1.2
  milestones as completed.

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
