# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Specification versions are date-stamped (`edp/YYYY-MM-DD`), not semver. SDK versions follow semver and declare which spec version(s) they implement.

## [Unreleased]

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
