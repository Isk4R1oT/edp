"""Three ClaudeAgentOptions definitions — conditions A/B/C of the EDP benchmark.

Locked at git tag `benchmark-prereg-v1`. Do not modify after that tag without
opening a new pre-registration cycle.

- A: bare agent, no extra block, no extra MCP server
- B: bare agent + EDP active block (per-turn hook) + 4 EDP MCP tools
     (verifier is OPTIONAL — pass verifier_enabled=True to enable the
     v0.2.0 PreToolUse verifier hook; default OFF for the main pre-
     registered study; ON only for the side mini-experiment)
- C: bare agent + same-token-mass placebo block + 4 noop fern_* MCP tools

Workspace isolation guarantee
-----------------------------
Each trajectory runs in its own `workspace/` directory under the run-dir.
Per-trajectory state — the `.edp/` SQLite store, the `.claude/settings.json`
file, the task's checkout — lives ONLY inside that workspace. Two parallel
runs of the same task with the same seed but different conditions cannot
see each other's `.edp` or `.claude` files; this is the structural
guarantee that allows the mini-experiment (B with verifier vs B without)
to be honest.

The on/off switch for EDP itself is the `setting_sources` and `mcp_servers`
options on `ClaudeAgentOptions`. Per Anthropic-primary docs:
  - `setting_sources=[]` disables filesystem settings entirely (SDK isolation)
  - `strict_mcp_config=True` ignores .mcp.json / plugins, surgical kill switch
  - `mcp_servers={}` is no MCP servers
References:
  - https://code.claude.com/docs/en/agent-sdk/hooks
  - https://code.claude.com/docs/en/agent-sdk/cost-tracking
  - .planning/research/benchmark-sdk-research.md §2
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from claude_agent_sdk import ClaudeAgentOptions

# Locked at pre-registration. Sonnet 4.6 for formal study, Haiku 4.5 for pilot,
# Opus 4.7 confirmatory. The runner passes the model in; this module does not
# hard-code it.
ConditionName = Literal["A", "B", "C"]

# Core tools available in all three conditions. The non-EDP, non-fern tool set.
_CORE_ALLOWED_TOOLS: list[str] = [
    "Read",
    "Edit",
    "Write",
    "Bash",
    "Glob",
    "Grep",
]

# EDP MCP tool names as they appear to the agent after Claude Code namespaces them.
# Format: `mcp__<server_name>__<tool_name>`.
_EDP_TOOL_NAMES: list[str] = [
    "mcp__edp__edp_show",
    "mcp__edp__edp_check",
    "mcp__edp__edp_record",
    "mcp__edp__edp_supersede",
]

# Placebo MCP tool names. Same shape as EDP tool names but for the fern_* server.
_FERN_TOOL_NAMES: list[str] = [
    "mcp__fern__fern_show",
    "mcp__fern__fern_check",
    "mcp__fern__fern_record",
    "mcp__fern__fern_supersede",
]

# Max-turns cap for a single trajectory. 150 chosen to give 100-step tasks
# headroom while bounding runaway agents. Per SPEC.md §12.2.
MAX_TURNS: int = 150

# Max budget per trajectory in USD. Hard cap; ResultMessage will return
# subtype="error_max_budget_usd" if exceeded.
MAX_BUDGET_USD: float = 10.0

# Effort setting — Anthropic's recommendation for coding/agentic tasks.
EFFORT: str = "high"


def options_a(*, cwd: Path, model: str, seed: int, temperature: float) -> ClaudeAgentOptions:
    """Condition A: bare agent. No EDP, no placebo, no extra block."""
    return ClaudeAgentOptions(
        cwd=cwd,
        model=model,
        allowed_tools=list(_CORE_ALLOWED_TOOLS),
        permission_mode="acceptEdits",
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        effort=EFFORT,
        setting_sources=[],          # no filesystem hooks loaded
        strict_mcp_config=True,      # no .mcp.json, no plugins
        mcp_servers={},              # no MCP servers
        include_hook_events=True,    # captures any hook output for audit (none expected in A)
        env={
            "ENABLE_PROMPT_CACHING_1H": "1",
            "ANTHROPIC_API_SEED": str(seed),
            "ANTHROPIC_API_TEMPERATURE": str(temperature),
        },
    )


def setup_edp_workspace(cwd: Path, *, verifier_enabled: bool) -> Path:
    """Stage `cwd/.edp/` (empty store) and `cwd/.claude/settings.json` for condition B.

    Each call writes a fresh store and fresh hook config — no cross-trajectory
    state leak. Called from runner.run_one BEFORE query() so the SDK's
    setting_sources=["project"] finds the hooks at startup.

    Returns the `.edp/` path so the caller can pass it as EDP_STORE.

    verifier_enabled=False (default for pre-registered B):
        SessionStart + UserPromptSubmit hooks only. No PreToolUse.

    verifier_enabled=True (mini-experiment only):
        + PreToolUse hook on Edit | Write | Bash | str_replace_editor.
        Requires `pip install 'explicit-decision-protocol[verifier]'` +
        ANTHROPIC_API_KEY in the environment. Hook fails OPEN on missing
        infra so a misconfigured run still completes.
    """
    edp_store_path = cwd / ".edp"
    edp_store_path.mkdir(parents=True, exist_ok=True)

    # Touch the store so the SQLite file exists (DecisionStore.open is what
    # creates it on first record; we want it to exist for the hook).
    from edp.store import DecisionStore  # local import keeps benchmark importable without edp installed

    DecisionStore.open(edp_store_path)

    claude_dir = cwd / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings: dict = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": f"{sys.executable} -m edp.hook SessionStart"}
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": f"{sys.executable} -m edp.hook UserPromptSubmit"}
                    ],
                }
            ],
        }
    }
    if verifier_enabled:
        settings["hooks"]["PreToolUse"] = [
            {
                "matcher": "Edit|Write|Bash|str_replace_editor",
                "hooks": [
                    {"type": "command", "command": f"{sys.executable} -m edp.verifier_hook"}
                ],
            }
        ]
    (claude_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return edp_store_path


def options_b(
    *,
    cwd: Path,
    model: str,
    seed: int,
    temperature: float,
    verifier_enabled: bool = False,
) -> ClaudeAgentOptions:
    """Condition B: EDP active block + 4 MCP tools.

    Per-registered B (verifier_enabled=False, default): visibility-only EDP.
    Mini-experiment Bv (verifier_enabled=True): adds v0.2.0 PreToolUse
    verifier hook on write-class tools. The mini-experiment is NOT part of
    the pre-registered formal study; it lives in `mini_experiment.py`.

    Pre-requirements:
      - `edp-mcp-server` console script importable on PATH
      - Caller has run `setup_edp_workspace(cwd, verifier_enabled=...)` to
        stage `.edp/` and `.claude/settings.json` BEFORE calling this fn
      - `EDP_STORE` env points at the fresh `.edp/` under the run's workspace
      - If verifier_enabled: `[verifier]` extra installed + ANTHROPIC_API_KEY
    """
    edp_store_path = cwd / ".edp"
    return ClaudeAgentOptions(
        cwd=cwd,
        model=model,
        allowed_tools=list(_CORE_ALLOWED_TOOLS) + list(_EDP_TOOL_NAMES),
        permission_mode="acceptEdits",
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        effort=EFFORT,
        setting_sources=["project"],  # loads `.claude/settings.json` from cwd
        strict_mcp_config=False,
        mcp_servers={
            "edp": {
                "command": "edp-mcp-server",
                "args": [],
                "env": {"EDP_STORE": str(edp_store_path)},
            },
        },
        include_hook_events=True,    # captures EDP active block per turn
        env={
            "ENABLE_PROMPT_CACHING_1H": "1",
            "EDP_STORE": str(edp_store_path),
            "ANTHROPIC_API_SEED": str(seed),
            "ANTHROPIC_API_TEMPERATURE": str(temperature),
        },
    )


def options_c(*, cwd: Path, model: str, seed: int, temperature: float) -> ClaudeAgentOptions:
    """Condition C: placebo. Same-token-mass block + 4 noop fern_* tools.

    The placebo MCP server is shipped as `benchmark.placebo:main` and registered
    as the console script `fern-mcp-server` in `benchmark/pyproject.toml`. If
    that registration is not yet in place, the runner.py startup check fails
    loudly rather than silently running C without a placebo.
    """
    return ClaudeAgentOptions(
        cwd=cwd,
        model=model,
        allowed_tools=list(_CORE_ALLOWED_TOOLS) + list(_FERN_TOOL_NAMES),
        permission_mode="acceptEdits",
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        effort=EFFORT,
        setting_sources=["project"],  # loads `.claude/settings.json` (placebo hook)
        strict_mcp_config=False,
        mcp_servers={
            "fern": {
                "command": "fern-mcp-server",
                "args": [],
                "env": {},
            },
        },
        include_hook_events=True,    # captures placebo block per turn
        env={
            "ENABLE_PROMPT_CACHING_1H": "1",
            "ANTHROPIC_API_SEED": str(seed),
            "ANTHROPIC_API_TEMPERATURE": str(temperature),
        },
    )


def options_for(
    condition: ConditionName,
    *,
    cwd: Path,
    model: str,
    seed: int,
    temperature: float,
    verifier_enabled: bool = False,
) -> ClaudeAgentOptions:
    """Dispatch table for condition → ClaudeAgentOptions.

    `verifier_enabled` only takes effect for condition B; ignored for A and C
    where it would be meaningless. The runner passes it through when the
    mini-experiment is being executed.
    """
    if condition == "A":
        return options_a(cwd=cwd, model=model, seed=seed, temperature=temperature)
    if condition == "B":
        return options_b(
            cwd=cwd,
            model=model,
            seed=seed,
            temperature=temperature,
            verifier_enabled=verifier_enabled,
        )
    if condition == "C":
        return options_c(cwd=cwd, model=model, seed=seed, temperature=temperature)
    raise ValueError(f"Unknown condition: {condition!r}; expected one of A, B, C.")
