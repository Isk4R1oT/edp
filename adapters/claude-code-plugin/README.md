# EDP Claude Code adapter

Connects an EDP store to a Claude Code session so the agent sees the
`<edp:active>` block on every turn and can call the four EDP tools
(`edp_show`, `edp_check`, `edp_record`, `edp_supersede`) natively.

## Two forms

| Form | Status | When to use |
|---|---|---|
| **standalone** (`standalone/`) | ✅ works today | Recommended. Two hooks + an MCP server registration + six slash commands, dropped into `.claude/`. |
| **plugin manifest** (`plugin/`) | ⏳ waiting on [claude-code#16538](https://github.com/anthropics/claude-code/issues/16538) | Plugin-form `SessionStart` `additionalContext` is currently silently dropped by Claude Code. Will populate once that upstream bug is fixed. |

Both forms wrap the same Python hook (`standalone/hooks/edp_hook.py`) and
the same MCP server (`edp-mcp-server` from the Python SDK).

---

## Quick install (standalone, ~3 minutes)

### 1. Install the Python SDK

```sh
pip install explicit-decision-protocol
# or, from a local checkout:
pip install -e /path/to/edp/sdk-python
```

This puts two binaries on `PATH`: `edp` (CLI) and `edp-mcp-server` (MCP server entry point).

### 2. Initialize a store in your project

```sh
cd /path/to/your/project
edp init
edp record --title "Test decision" --decision "Just verifying install."
edp list --active   # should print DEC-0001
```

A `.edp/` directory now exists at your project root with `store.db` and a `decisions/` markdown projection.

### 3. Drop the Claude Code config into `.claude/`

```sh
mkdir -p .claude/commands
cp /path/to/edp/adapters/claude-code-plugin/standalone/settings.json.example .claude/settings.json
cp /path/to/edp/adapters/claude-code-plugin/standalone/.mcp.json.example .claude/.mcp.json
cp /path/to/edp/adapters/claude-code-plugin/standalone/commands/*.md .claude/commands/
```

Then **edit the two `*.example` paths** to point at your actual checkout:

- `settings.json`: replace `ABSOLUTE/PATH/TO/edp/...` with the real absolute path to `edp_hook.py`.
- `.mcp.json`: `EDP_STORE` defaults to `${PWD}/.edp` — usually fine; override if your store lives elsewhere.

### 4. Start Claude Code in the project directory

```sh
claude
```

On the first user turn, `edp_hook.py` runs as a `UserPromptSubmit` hook, calls `edp inject`, and prepends the active block (`<edp:active version="1">…`) to the conversation context. The MCP server is auto-started so the four tools are available.

### 5. Verify

In a Claude Code session, type:

```
/edp-list
```

If it prints your decisions, the MCP server is connected. Then try:

```
What does the active EDP block say? Quote it verbatim.
```

The model should quote your seeded `DEC-0001` snippet word-for-word. If it can't, the hook isn't injecting (see Troubleshooting).

---

## What you get

### Hook (`standalone/hooks/edp_hook.py`)
A small Python script that fires on `SessionStart` and `UserPromptSubmit`. It:
- Walks up from cwd to find the nearest `.edp/`
- Bumps a per-session monotonic version counter (`.edp/.session_version`)
- Calls `edp inject --version N` (with `--primer` on `SessionStart`)
- Emits `hookSpecificOutput.additionalContext` per the Claude Code hook protocol

Fail-soft by design: no `.edp/`, no `edp` binary, hook script error — none of these break your Claude Code session, they just silently skip the injection that turn.

### Protocol primer (auto-injected, no `CLAUDE.md` required)

You do **not** need to write anything in your project's `CLAUDE.md` to use
EDP. The `SessionStart` hook injects a one-time ~280-token **protocol
primer** describing the four tools, the autonomous stance, and the
`provisional` flag. An agent that has never seen EDP before discovers it
through that primer on its first turn.

Per-turn (`UserPromptSubmit`) injections omit the primer — only the active
snippet block is repeated — to keep ongoing token cost minimal.

This is what makes the blank-slate trial at
[`docs/dogfood-tinycache.md`](../../docs/dogfood-tinycache.md) work: empty
`CLAUDE.md`, empty store, no user prompt mentioning EDP, and the agent
still records and supersedes decisions autonomously.

### MCP server (`edp-mcp-server`)
Registered in `.mcp.json` so Claude Code starts it automatically. Exposes:
- 4 tools: `edp_show`, `edp_check`, `edp_record`, `edp_supersede` (with correct MCP annotations — reads do not trigger destructive-confirm prompts)
- 2 resources: `decisions://active` (current snippet block), `events://recent` (last 20 audit log entries)

### Slash commands (`standalone/commands/edp-*.md`)
- `/edp-record <title>` — capture a new decision, asks for missing fields
- `/edp-show DEC-NNNN` — fetch full body when the snippet isn't enough
- `/edp-check <action>` — soft-check a planned action against active decisions
- `/edp-supersede DEC-NNNN` — formally replace an active decision (preserves chain)
- `/edp-list [filters]` — list decisions in the store
- `/edp-events [--decision DEC-NNNN]` — read the append-only audit log

---

## Troubleshooting

### The model doesn't see the active block
1. Run Claude Code with `--debug hooks` to see whether the hook fires and what it returns.
2. Verify the hook script path in `.claude/settings.json` is absolute and the file is executable (`chmod +x edp_hook.py`).
3. Verify `edp inject` works manually from the project root: `edp inject --version 99` should print an `<edp:active>` block.
4. If `edp` isn't on `PATH` (common when installed in a venv), set `EDP_BIN` in `settings.json`:
   ```json
   "command": "python3 PATH/TO/edp_hook.py UserPromptSubmit",
   "env": {"EDP_BIN": "/path/to/.venv/bin/edp"}
   ```

### `additionalContext` accumulates over many turns
This is [claude-code#40216](https://github.com/anthropics/claude-code/issues/40216). The hook mitigates it: every block carries `version="N"` with an explicit precedence line telling the model to use only the latest version. Older blocks remain in transcript but the model is instructed to ignore them.

### `SessionStart` hook fires but no context appears
Standalone-form `SessionStart` works. **Plugin-form** SessionStart is currently broken upstream ([#16538](https://github.com/anthropics/claude-code/issues/16538)) — that's why this adapter ships as standalone first.

### Multiple instances of `edp-mcp-server` running
Claude Code starts the MCP server per session. That's expected — SQLite WAL + `busy_timeout=5000` (per SPEC §7.4) handles concurrent writers. If you see persistent `SQLITE_BUSY`, raise the retry budget in `store.py` or pin to a single writer.

---

## Uninstall

```sh
rm -rf .claude/settings.json .claude/.mcp.json .claude/commands/edp-*.md
# .edp/ store stays — keep your decisions or rm -rf to drop them
```

---

## Status

- Hook tested via `pytest adapters/claude-code-plugin/tests/` — 7 cases covering JSON emission, upward `.edp/` discovery, version monotonicity, silent-passthrough behavior, `EDP_STORE` env override, precedence-line presence.
- End-to-end smoke against a live Claude Code session: **not automated here** — instructions above describe the manual verification step.

See top-level `SPEC.md` for the protocol contract, `EXAMPLE.md` for an agent-session walkthrough, and `tests/integration/langgraph_demo.py` for a real-LLM proof of the loop.
