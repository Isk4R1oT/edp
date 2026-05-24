# EDP MCP-server adapter

Exposes an EDP store as a [Model Context Protocol](https://modelcontextprotocol.io) server. Use this with any MCP-capable client (Cursor, Cline, Continue, Claude Desktop, ChatGPT Apps, mcp-inspector) when you do not have a harness-native EDP adapter.

The server is shipped as the **`edp-mcp-server`** console script of the core SDK — no separate install. It conforms to MCP spec version `2025-06-18` (stdio transport).

---

## What it exposes

### Tools (4)

| Tool | Annotations | Purpose |
|---|---|---|
| `edp_show` | `readOnlyHint=true, idempotentHint=true` | Fetch full body of one decision by id |
| `edp_check` | `readOnlyHint=true, idempotentHint=false` | Soft-check a planned action against active decisions (lexical) |
| `edp_record` | `destructiveHint=false` | Create a new decision; returns DEC-NNNN |
| `edp_supersede` | `destructiveHint=true` | Replace existing decision; chain preserved |

All four have spec-correct annotations per MCP 2025-06-18 — reads do NOT trigger destructive-confirm prompts in Claude Code / Cline.

### Resources (2)

| URI | Purpose |
|---|---|
| `decisions://active` | Current `<edp:active>` snippet block (for clients with auto-fetch resources) |
| `events://recent` | Last 20 entries from the append-only audit log |

⚠️ Resources are **pull-only** in every mainstream client today — no major harness auto-prepends them every turn. Use a harness-native adapter (Claude Code hook, LangGraph middleware) if you need automatic per-turn injection. This MCP adapter is best for the on-demand tool path.

---

## Install per client

The pattern is the same everywhere: register `edp-mcp-server` as an MCP server with `EDP_STORE` pointing at your `.edp/` directory.

### Prerequisite (any client)

```sh
pip install explicit-decision-protocol     # or pip install -e /path/to/edp/sdk-python
cd /path/to/your/project
edp init
edp record --title "test" --decision "verifying install"
```

### Claude Code

In `<your-project>/.mcp.json` (or merge with existing):

```json
{
  "mcpServers": {
    "edp": {
      "command": "edp-mcp-server",
      "args": [],
      "env": { "EDP_STORE": "${PWD}/.edp" }
    }
  }
}
```

If `edp-mcp-server` is not on PATH (venv install), use the absolute path:

```json
"command": "/path/to/.venv/bin/edp-mcp-server"
```

Verify: in a session, ask the model to call `edp_show("DEC-0001")` — it should return your test record.

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the platform equivalent:

```json
{
  "mcpServers": {
    "edp": {
      "command": "/absolute/path/to/.venv/bin/edp-mcp-server",
      "env": { "EDP_STORE": "/absolute/path/to/project/.edp" }
    }
  }
}
```

Restart Claude Desktop. The four tools appear in the tools picker.

### Cursor

`Cursor Settings → MCP → Add new MCP server`. Configuration shape:

```json
{
  "mcpServers": {
    "edp": {
      "command": "/absolute/path/to/.venv/bin/edp-mcp-server",
      "env": { "EDP_STORE": "/absolute/path/to/project/.edp" }
    }
  }
}
```

Cursor's 40-tool ceiling matters: EDP adds only 4 tools, leaves room.

### Cline

`Cline → MCP Servers → Edit MCP Settings` produces the same JSON shape as Cursor. Cline supports stdio transport natively.

### Continue.dev

In `~/.continue/config.json` (or `config.ts`):

```json
{
  "mcpServers": [
    {
      "name": "edp",
      "command": "/absolute/path/to/.venv/bin/edp-mcp-server",
      "env": { "EDP_STORE": "/absolute/path/to/project/.edp" }
    }
  ]
}
```

### Any generic MCP client

`edp-mcp-server` speaks stdio JSON-RPC per MCP spec 2025-06-18. Run it directly:

```sh
EDP_STORE=/path/to/project/.edp edp-mcp-server < /dev/stdin
```

Send `initialize` → `tools/list` → `resources/list` to negotiate.

---

## Smoke test (no client needed)

Verify the server responds to MCP protocol probes with the `mcp-inspector`-style smoke script in this directory:

```sh
cd adapters/mcp-server
python3 smoke.py /path/to/project/.edp
```

Expected output:
```
✓ initialize OK (protocolVersion=2025-06-18)
✓ tools/list returns 4 tools
✓ resources/list returns 2 resources
✓ edp_show round-trips a Decision
✓ decisions://active returns an <edp:active> block
```

---

## Known limitations

- **Resources are pull-only.** No client auto-prepends `decisions://active` per turn. Use a harness-native adapter for auto-injection.
- **Per spec §8.3:** pin to stdio on Windows until [fastmcp#4192](https://github.com/jlowin/fastmcp/issues/4192) (HTTP transport SSE-task leak after ~12 sessions) ships a fix. The reference server defaults to stdio.
- **Multiple instances per project.** Each MCP client typically starts its own `edp-mcp-server` process. SQLite WAL + `busy_timeout=5000` per SPEC §7.4 handles concurrent writers.

---

## Status

- Core MCP server implementation: `sdk-python/edp/server.py`
- This adapter directory: install-matrix docs + smoke test
- Tools/annotations: covered by SDK unit tests (`sdk-python/tests/test_store.py`, etc.)
- Real-LLM tool path: covered by `tests/integration/langgraph_demo.py` (which exercises the same four functions via the LangGraph binding — the MCP path wraps the same store methods)
