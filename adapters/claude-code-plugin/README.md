# EDP Claude Code Plugin

Claude Code plugin that connects an EDP store to your Claude Code session.

## What it does

- **`SessionStart` hook** — on session start / resume, runs `edp inject` and pushes the active block into the initial context
- **`UserPromptSubmit` hook** — on every user turn, refreshes the active block (with `version="N"` marker to avoid the known accumulation bug, see SPEC §8.2)
- **Plugin commands** — exposes the four core tools (`show`, `check`, `record`, `supersede`) as plugin commands the agent can call

## Status

Scaffolding. Awaiting Python SDK so the hooks have something to call.

## Planned layout

```
adapters/claude-code-plugin/
├── plugin.json                # plugin manifest
├── README.md
├── hooks/
│   ├── session-start.sh       # invokes `edp inject` from the project's .edp/
│   └── user-prompt-submit.sh  # same, every turn, with version bump
└── commands/
    ├── edp-show.md
    ├── edp-check.md
    ├── edp-record.md
    └── edp-supersede.md
```

## Known limitations (from injection research)

- Claude Code `UserPromptSubmit` `additionalContext` accumulates in history (see [#40216](https://github.com/anthropics/claude-code/issues/40216)). Mitigation: include `<edp:active version="N">` so model uses only the latest block.
- `additionalContext` cap ~10k chars. Active block target ≤2k tokens.
- Skills cannot be used for unconditional injection — they load only when Claude judges the description relevant. Hence the hook approach.
