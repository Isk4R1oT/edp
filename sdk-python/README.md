# EDP — Explicit Decision Protocol (Python SDK)

Reference implementation of the [Explicit Decision Protocol](https://github.com/Isk4R1oT/edp) in Python.

**Status:** v0.1 alpha — implements spec version `edp/2026-05-24`. Conformance breaking changes may still happen before v1.0.

## What this is

EDP is a small protocol that gives AI agents an external working memory of their architectural decisions, so they can remember and respect them across long sessions and across multiple sessions. The agent records commitments via four tools (`record`, `show`, `check`, `supersede`), the SDK stores them in a local SQLite store, and an adapter injects a 2–4 line snippet of each active decision into the agent's context on every turn.

Full problem statement, evidence, and a real two-session dogfood trace on Opus 4.7 are at the [top-level README](https://github.com/Isk4R1oT/edp#readme).

## Install

```sh
pip install explicit-decision-protocol            # core SDK + CLI + MCP server
pip install "explicit-decision-protocol[langgraph]"  # + LangGraph binding (langchain >= 1.1)
```

This installs two console scripts on `PATH`:
- `edp` — the CLI (`edp init`, `edp record`, `edp list`, `edp show`, `edp supersede`, `edp inject`, `edp events`)
- `edp-mcp-server` — an MCP stdio server exposing the four EDP tools to any MCP client (Claude Code, Claude Desktop, Cursor, Cline, Continue)

## Quick start — Python

```python
from edp import DecisionStore

store = DecisionStore.open(".edp")

dec_id = store.record(
    title="Cache miss is an exception, not a None sentinel",
    decision="Cache.get raises CacheMiss (a KeyError subclass) on miss.",
    key_constraints=[
        "Cache.get must raise on miss, never return a sentinel",
        "CacheMiss remains a KeyError subclass for backwards compatibility",
    ],
    revision_conditions=[],  # event-based re-examination triggers
    evidence=["src/cache.py:CacheMiss"],
    tags=["api-surface"],
    confidence=0.9,
    actor="human:you",
)
print(dec_id)  # "DEC-0001"

# Later: render the active block your agent should see
from edp.selector import get_active_block

block = get_active_block(store, version=1)
print(block.text)
# <edp:active version="1">
# DEC-0001 [active] conf=0.9
#   Title: Cache miss is an exception, not a None sentinel
#   ...
# </edp:active>
```

## Quick start — CLI

```sh
cd your-project
edp init
edp record --title "your first decision" --decision "..." --constraint "..." --evidence "@..."
edp list --active
edp inject --version 1     # prints the <edp:active> block; pipe to hook stdout
```

## Quick start — LangGraph

```python
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from edp import DecisionStore
from edp.bindings.langgraph import edp_tools, edp_before_model

store = DecisionStore.open(".edp")

agent = create_agent(
    model=ChatOpenAI(model="gpt-4.1-mini"),
    tools=edp_tools(store),
    middleware=[edp_before_model(store)],  # MUST be ordered before SummarizationMiddleware
)
```

Two runnable examples (auto-pick the model based on `OPENROUTER_API_KEY` / `OPENAI_API_KEY`) are at `adapters/middleware-langgraph/examples/` in the [main repo](https://github.com/Isk4R1oT/edp/tree/main/adapters/middleware-langgraph/examples).

## Quick start — Claude Code

The standalone hooks adapter wires up `SessionStart` (injects a protocol primer + active block) and `UserPromptSubmit` (injects active block per turn). Setup is ~3 minutes:

```sh
cd your-project
edp init

# Clone the EDP repo to get the adapter files (these are not on PyPI yet):
git clone https://github.com/Isk4R1oT/edp.git ~/edp

# Drop the standalone CC config into .claude/:
mkdir -p .claude/commands
cp ~/edp/adapters/claude-code-plugin/standalone/settings.json.example .claude/settings.json
cp ~/edp/adapters/claude-code-plugin/standalone/.mcp.json.example .claude/.mcp.json
cp ~/edp/adapters/claude-code-plugin/standalone/commands/*.md .claude/commands/

# Edit .claude/settings.json — replace ABSOLUTE/PATH/TO/edp/... with $HOME/edp/...

claude  # session starts; agent now sees the active block + primer
```

Full Claude Code install matrix, MCP-client variants (Cursor, Cline, Continue, Claude Desktop), and the LangGraph adapter docs are in the [main repo](https://github.com/Isk4R1oT/edp#quick-install).

## What's in the box

| Module | Purpose |
|---|---|
| `edp.models` | Pydantic `Decision` model, `Status` enum, `Alternative` |
| `edp.store` | SQLite store (WAL + FTS5 + append-only events table + markdown projection) |
| `edp.selector` | Builds the `<edp:active>` snippet block with token-budget + trim policy |
| `edp.render` | Snippet rendering, full-body markdown, `PROTOCOL_PRIMER` constant |
| `edp.server` | FastMCP 3.x server exposing the four tools + two resources |
| `edp.cli` | Typer CLI (`init`, `record`, `list`, `show`, `inject`, `events`, `supersede`, `due`) |
| `edp.bindings.langgraph` | LangChain v1.1+ `AgentMiddleware` + helper `inject_into_messages` |

48 unit tests, 9 Claude-Code-hook tests, 5/5 MCP protocol probes, 6/6 explicit-prompt LangGraph integration, 2/3 naturalistic-prompt LangGraph integration (honest snippet-first failure on turn 2).

## Dependencies

- `fastmcp >= 3.3, < 4.0` — MCP server framework
- `pydantic >= 2.0, < 3.0` — schema models
- `typer >= 0.12, < 1.0` — CLI
- (optional `[langgraph]`) `langchain >= 1.1`, `langgraph >= 0.2`

No vector store, no embeddings, no semantic search in v0.1. SQLite FTS5 (built-in) covers full-text needs.

## License

MIT — see the [top-level repo](https://github.com/Isk4R1oT/edp/blob/main/LICENSE) for the full text.
