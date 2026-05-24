# EDP MCP-server Adapter

A FastMCP 3.x server that exposes an EDP store as an MCP server. Use this with any MCP-capable client (Cursor, Cline, Continue, etc.) when you don't have a harness-native EDP adapter.

## What it exposes

**Tools:**
- `edp.show(id)`
- `edp.check(planned_action)`
- `edp.record(...)`
- `edp.supersede(old_id, new_record)`

**Resources:**
- `decisions://active` — the current active block, for MCP clients that auto-fetch resources

## Limitation to be aware of

MCP resources are **pull-not-push** in every mainstream client. No client currently auto-prepends `decisions://active` on every turn. This adapter is therefore best for:

- On-demand tool use (`show`, `check`, `record`, `supersede`) — always works
- Sessions where the agent is instructed (via system prompt or rules file) to fetch `decisions://active` at session start

For automatic every-turn injection, use a harness-native adapter (the Claude Code plugin for Claude Code; LangGraph middleware for LangGraph, etc).

## Status

Scaffolding. Will be built as a thin wrapper over the Python SDK once that lands.

## Planned layout

```
adapters/mcp-server/
├── pyproject.toml
├── README.md
└── edp_mcp/
    ├── __init__.py
    └── server.py        # FastMCP server: 4 tools + 1 resource
```
