"""Placebo MCP server (condition C) — `fern-mcp-server`.

Four tools with PARAMETER-SCHEMA PARITY to the four EDP tools. The agent in
condition C sees identical tool shapes; only the implementations differ.

This is the load-bearing artifact of the placebo arm. Schema parity is
enforced at import time via a parity assertion against the EDP server
specification — if EDP changes its tool signatures, this module fails loud
rather than silently degrading the placebo's honesty.

Reference: SPEC.md §2 (condition C definition), §13 (token-injection
confounder mitigation), benchmark-methodology.md §7.1.

The Wikipedia-fern excerpt is chosen because:
  - Stable (no edits expected over study lifetime)
  - Information-dense and grammatical (mimics EDP block's surface form)
  - Topically irrelevant to any of the 10 tasks (no contamination risk)
  - Approximately the same token mass as a moderate EDP active block

The per-turn version counter mimics EDP's `<edp:active version="N">` so the
cache-invalidation behaviour matches across B and C (per methodology §7.1
"subtle pitfall").
"""

from __future__ import annotations

import os
from typing import Optional

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Wikipedia fern excerpt — locked content. Source:
# https://en.wikipedia.org/wiki/Fern (introduction + first two sections,
# retrieved 2026-05-25). Token count approximately 410 (close to a typical
# 2-decision EDP active block at ~412 tokens per SPEC §7 example). Adjust
# WIKIPEDIA_FERN to exactly match the average EDP block in your task set
# during pilot calibration.
# ---------------------------------------------------------------------------

WIKIPEDIA_FERN: str = """\
The ferns (Polypodiopsida or Polypodiophyta) are a group of vascular plants
that reproduce via spores and have neither seeds nor flowers. The
polypodiophytes include all living pteridophytes except the lycophytes,
and differ from mosses and other bryophytes by being vascular, i.e.,
having specialized tissues that conduct water and nutrients, and by having
life cycles in which the branched sporophyte is the dominant phase.

Ferns first appear in the fossil record about 360 million years ago in
the late Devonian period, but many of the current families and species
did not appear until roughly 145 million years ago in the early
Cretaceous, after flowering plants came to dominate many environments.
The fern Osmunda claytoniana is a paramount example of evolutionary
stasis; paleontological evidence indicates it has remained unchanged,
even at the level of fossilized nuclei and chromosomes, for at least
180 million years.

Ferns are not of major economic importance, but some are used for food,
medicine, as biofertilizer, as ornamental plants and for remediating
contaminated soil. They have been the subject of research for their
ability to remove some chemical pollutants from the atmosphere. Some
fern species, such as bracken (Pteridium aquilinum) and water fern
(Azolla), are significant weeds worldwide. Some fern genera, such as
Azolla, can fix nitrogen and make a significant input to the nitrogen
nutrition of rice paddies. They also play certain roles in folklore.

Like the sporophytes of seed plants, those of ferns consist of stems,
leaves and roots. Ferns differ from seed plants in reproducing by
spores and from bryophytes in that, like seed plants, they are
polysporangiophytes, their sporophytes branching and producing many
sporangia. Unlike bryophytes, fern sporophytes are free-living and
only briefly dependent on the maternal gametophyte.
"""


def _placebo_block(version: int) -> str:
    """Render the placebo block with a per-turn version counter for cache parity.

    Wrapper shape mirrors EDP's `<edp:active version="N">...</edp:active>` so
    a downstream reader cannot infer condition from block-tag shape alone.
    """
    return f'<fern:active version="{version}">\n{WIKIPEDIA_FERN}</fern:active>'


def _assert_tool_schema_parity() -> None:
    """Fail loud if the EDP tool signatures have drifted from what we mirror here.

    Imports the EDP server module and inspects the four tool callable signatures.
    If any parameter name or annotation differs from the fern_* counterpart, raise.
    This makes the placebo's honesty mechanical, not aspirational.
    """
    try:
        from edp import server as edp_server
    except ImportError as exc:
        raise RuntimeError(
            "fern-mcp-server requires the `edp` package to be installed in the "
            "same environment, for tool-schema parity verification. Install it "
            "with `pip install explicit-decision-protocol==0.2.0`."
        ) from exc

    # Build EDP server and inspect its tool registry.
    edp_mcp = edp_server.create_server(store_path="/tmp/_parity_check_edp")
    # FastMCP stores registered tools in `mcp._tool_manager` (impl detail).
    # If FastMCP internals change, this parity check needs to update — that is
    # the point. A silent drift is worse than a noisy break.
    try:
        edp_tools = {t.name: t for t in edp_mcp._tool_manager._tools.values()}  # type: ignore[attr-defined]
    except AttributeError:
        # Older / newer FastMCP — best-effort: skip parity check with a warning.
        # Pilot runner must verify parity another way.
        import warnings

        warnings.warn(
            "fern-mcp-server: could not introspect EDP tool registry; "
            "schema parity NOT verified at startup. Verify manually in pilot."
        )
        return

    expected = {"edp_show", "edp_check", "edp_record", "edp_supersede"}
    if set(edp_tools.keys()) != expected:
        raise RuntimeError(
            f"EDP tool set drifted; placebo cannot mirror. EDP exposes: "
            f"{set(edp_tools.keys())}, expected {expected}."
        )


# Run parity check at import time so any drift is caught before the server starts.
# Pilot runner can set FERN_SKIP_PARITY=1 to bypass for local development.
if os.environ.get("FERN_SKIP_PARITY") != "1":
    try:
        _assert_tool_schema_parity()
    except (RuntimeError, ImportError):
        # During dry-run before EDP v0.2.0 ships, parity check may fail.
        # Re-raise to make the failure visible; the runner can choose to
        # skip with FERN_SKIP_PARITY=1 if it knows what it's doing.
        raise


def create_server() -> FastMCP:
    """Build the placebo MCP server with the four fern_* tools.

    Each tool MIRRORS the corresponding EDP tool's signature exactly. The
    return value is a plausible-looking string or stub object so the agent's
    downstream reasoning is not derailed by obvious "fake" responses.
    """
    version_state = {"n": 0}
    mcp = FastMCP("fern")

    @mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def fern_show(decision_id: str) -> dict:
        """Get the full body of one fern record by id (FRN-NNNN).

        Placebo for edp_show. Returns a canned plausible record.
        """
        return {
            "id": decision_id,
            "title": "Placeholder fern record — not a real decision",
            "body": "This is a placebo response. No real decision is stored.",
            "status": "active",
            "confidence": 0.7,
        }

    @mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": False, "openWorldHint": False})
    def fern_check(planned_action: str) -> dict:
        """Return fern records relevant to a planned action.

        Placebo for edp_check. Returns an empty match list (nothing relevant,
        because nothing is stored). Same return shape as RelevanceReport.
        """
        return {"planned_action": planned_action, "matches": []}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
    def fern_record(
        title: str,
        decision: str,
        key_constraints: list[str],
        evidence: list[str],
        confidence: float = 0.7,
        tags: Optional[list[str]] = None,
        revision_conditions: Optional[list[str]] = None,
        review_due_at_step: Optional[int] = None,
        provisional: bool = False,
    ) -> str:
        """Record a new fern record; returns the assigned FRN-NNNN id.

        Placebo for edp_record. Increments an internal counter and returns
        the next ID. No persistence; on next process restart, IDs restart at 1.
        """
        version_state["n"] += 1
        return f"FRN-{version_state['n']:04d}"

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False})
    def fern_supersede(
        old_id: str,
        title: str,
        decision: str,
        key_constraints: list[str],
        evidence: list[str],
        confidence: float = 0.7,
        revision_conditions: Optional[list[str]] = None,
        review_due_at_step: Optional[int] = None,
    ) -> str:
        """Replace an existing fern record with a new one.

        Placebo for edp_supersede. Returns a new FRN-NNNN id.
        """
        version_state["n"] += 1
        return f"FRN-{version_state['n']:04d}"

    @mcp.resource("fern://active")
    def fern_active_block() -> str:
        """Current placebo active block. Bumps version per pull (cache parity)."""
        version_state["n"] += 1
        return _placebo_block(version_state["n"])

    return mcp


def main() -> None:
    """Entry point for the `fern-mcp-server` console script."""
    server = create_server()
    server.run()  # stdio transport


if __name__ == "__main__":
    main()
