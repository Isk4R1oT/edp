# EDP Python SDK

Reference implementation of the Explicit Decision Protocol in Python, built on [FastMCP 3.x](https://github.com/jlowin/fastmcp).

Conforms to spec version `edp/2026-05-24`.

## Status

Scaffolding — not yet implemented. See top-level `SPEC.md` for the protocol contract this SDK implements.

## Planned layout

```
sdk-python/
├── pyproject.toml
├── README.md
└── edp/
    ├── __init__.py
    ├── models.py       # Pydantic models for Decision record
    ├── store.py        # SQLite + append-only events + FTS5
    ├── selector.py     # Active-block builder
    ├── render.py       # Decision → snippet, full body, markdown export
    ├── tools.py        # show / check / record / supersede
    └── cli.py          # `edp init / record / list / inject / show`
```

## Planned dependencies

- `fastmcp >= 3.0` — MCP server framework
- `pydantic >= 2.0` — schema models
- `sqlite-utils` or stdlib `sqlite3` — storage (no external db)
- `click` or `typer` — CLI

No vector store, no embeddings, no semantic search in v0.1. SQLite FTS5 (built-in) covers full-text needs.

## Installation (planned)

```sh
pip install explicit-decision-protocol
```

## CLI surface (planned)

```sh
edp init                            # create .edp/ in cwd
edp record --title "..." ...        # interactive or arg-driven
edp list --active                   # list active decisions
edp show DEC-0042                   # full body
edp inject                          # print active block (for hook subprocess)
edp supersede DEC-0042 --title "..."
```
