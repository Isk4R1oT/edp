"""FastMCP 3.x server exposing the four EDP tools + the active-block resource.

Implements §5 (tools) and §13 (MCP server adapter reference impl).
Transport: stdio (per §8.3, until fastmcp#4192 resolves on Windows).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from edp.selector import get_active_block
from edp.store import DecisionStore


def create_server(store_path: str | Path = ".edp") -> FastMCP:
    """Create a FastMCP server bound to a DecisionStore."""
    store = DecisionStore.open(store_path)
    # Per-server monotonic version counter for the active block. Resets on restart;
    # adapters that need persistence across restarts can read it from a side file.
    version_state = {"n": 0}
    mcp = FastMCP("edp")

    @mcp.tool
    def edp_show(decision_id: str) -> dict:
        """Get the full body of one EDP decision by id (DEC-NNNN).

        Use this when you need the reasoning, evidence, alternatives, or full
        history of a decision — not just the snippet you see in the active block.
        """
        return store.show(decision_id).model_dump(mode="json")

    @mcp.tool
    def edp_check(planned_action: str) -> dict:
        """Return EDP active decisions relevant to a planned action.

        Call this BEFORE risky or scope-affecting actions to see whether any
        active decision constrains what you are about to do. Soft check — does
        not block; you decide what to do with the returned matches.
        """
        return store.check(planned_action).model_dump(mode="json")

    @mcp.tool
    def edp_record(
        title: str,
        decision: str,
        key_constraints: list[str],
        evidence: list[str],
        confidence: float = 0.7,
        tags: Optional[list[str]] = None,
        review_due_at_step: Optional[int] = None,
        provisional: bool = True,
    ) -> str:
        """Record a new EDP decision; returns the assigned DEC-NNNN id.

        Decisions you author should normally be marked provisional=True so a
        human can confirm before the decision becomes binding on future work.
        """
        return store.record(
            title=title,
            decision=decision,
            key_constraints=key_constraints,
            evidence=evidence,
            confidence=confidence,
            tags=tags or [],
            actor="agent",
            review_due_at_step=review_due_at_step,
            provisional=provisional,
        )

    @mcp.tool
    def edp_supersede(
        old_id: str,
        title: str,
        decision: str,
        key_constraints: list[str],
        evidence: list[str],
        confidence: float = 0.7,
        review_due_at_step: Optional[int] = None,
    ) -> str:
        """Replace an existing decision with a new one; archives the old, preserves the chain."""
        return store.supersede(
            old_id,
            title=title,
            decision=decision,
            key_constraints=key_constraints,
            evidence=evidence,
            confidence=confidence,
            review_due_at_step=review_due_at_step,
            actor="agent",
        )

    @mcp.resource("decisions://active")
    def active_block() -> str:
        """Current EDP active-decisions block.

        Note: per §8 of the spec, MCP resources are pull-only in mainstream
        clients. Per-turn auto-injection requires a harness-native adapter
        (Claude Code hook, LangGraph middleware, etc).
        """
        version_state["n"] += 1
        result = get_active_block(store, version=version_state["n"])
        return result.text

    return mcp


def main() -> None:
    """Entry point for `edp-mcp-server` console script."""
    import os

    store_path = os.environ.get("EDP_STORE", ".edp")
    server = create_server(store_path)
    server.run()  # stdio transport by default


if __name__ == "__main__":
    main()
