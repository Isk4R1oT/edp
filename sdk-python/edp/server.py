"""FastMCP 3.x server exposing the four EDP tools + the active-block resource.

Implements §5 (tools) and §13 (MCP server adapter reference impl).
Transport: stdio (per §8.3, until fastmcp#4192 resolves on Windows).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from edp.models import Decision, RelevanceReport
from edp.selector import get_active_block
from edp.store import DecisionStore

# MCP tool annotations per MCP spec 2025-06-18. Defaults are
# "destructive + open-world" — relying on them would make every read in
# Claude Code / Cline trigger a confirm prompt. Spec §8.1 requires
# adapters to set these explicitly.
_READ_ANNOTATIONS = {
    "readOnlyHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}
_CHECK_ANNOTATIONS = {
    "readOnlyHint": True,
    "idempotentHint": False,  # FTS results may shift as new records land
    "openWorldHint": False,
}
_CREATE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,  # record() creates; never destroys
    "idempotentHint": False,
    "openWorldHint": False,
}
_SUPERSEDE_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,  # mutates the old record's status
    "idempotentHint": False,
    "openWorldHint": False,
}


def create_server(store_path: str | Path = ".edp") -> FastMCP:
    """Create a FastMCP server bound to a DecisionStore."""
    store = DecisionStore.open(store_path)
    # Per-server monotonic version counter for the active block. Resets on restart;
    # adapters that need persistence across restarts can read it from a side file.
    version_state = {"n": 0}
    mcp = FastMCP("edp")

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    def edp_show(decision_id: str) -> Decision:
        """Get the full body of one EDP decision by id (DEC-NNNN).

        Use this when you need the reasoning, evidence, alternatives, or full
        history of a decision — not just the snippet you see in the active block.

        Example:
            edp_show("DEC-0042")  →  Decision with full body, supersede chain,
                                     review history, and all evidence handles.
        """
        return store.show(decision_id)

    @mcp.tool(annotations=_CHECK_ANNOTATIONS)
    def edp_check(planned_action: str) -> RelevanceReport:
        """Return EDP active decisions relevant to a planned action.

        Call this BEFORE risky or scope-affecting actions to see whether any
        active decision constrains what you are about to do. Soft check — does
        not block; you decide what to do with the returned matches.

        Mechanism note: matching is lexical (SQLite FTS5 word-overlap on
        title + decision + key_constraints), NOT semantic. Phrase your
        planned_action with the same vocabulary your decisions use, or call
        edp_show on any decision you suspect applies but didn't surface here.

        Example:
            edp_check("send outreach to SMB-segment leads")
              →  [{id: "DEC-0042", relevance: 0.91, why: "constraint match: enterprise only"}]
        """
        return store.check(planned_action)

    @mcp.tool(annotations=_CREATE_ANNOTATIONS)
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
        Use the decision-worthiness criteria from spec §3.7 — record only when
        a commitment has multi-turn consequence, is constraint-shaped, hard
        to re-derive, or has reversibility implications.

        Example:
            edp_record(
                title="Vector storage: pgvector in existing Postgres",
                decision="All vector storage uses pgvector. No new infra.",
                key_constraints=["no new infra deps", "cosine and L2 supported"],
                evidence=["@session_log/step_47/research"],
                confidence=0.85,
            )  →  "DEC-0051"
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

    @mcp.tool(annotations=_SUPERSEDE_ANNOTATIONS)
    def edp_supersede(
        old_id: str,
        title: str,
        decision: str,
        key_constraints: list[str],
        evidence: list[str],
        confidence: float = 0.7,
        review_due_at_step: Optional[int] = None,
    ) -> str:
        """Replace an existing EDP decision with a new one; archives the old, preserves the chain.

        The old record stays in storage with status=superseded and a
        superseded_by pointer to the new record. The new record carries
        a supersedes back-pointer. The full chain is preserved for audit.

        Use this — never edit an existing decision — when an active decision
        needs to change. If old_id is already superseded the call fails.

        Example:
            edp_supersede(
                "DEC-0042",
                title="Enterprise focus broadened to enterprise + mid-market",
                decision="...",
                key_constraints=["enterprise OR mid-market", "min 100 employees"],
                evidence=["@session_log/step_120/user_clarification"],
                confidence=0.85,
            )  →  "DEC-0053"
        """
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
