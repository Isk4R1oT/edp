"""Render Decision records as snippet (active block) or full markdown body.

Implements §4 (Active block format) and the markdown projection of §7.3.
"""

from __future__ import annotations

from edp.models import Decision


# Protocol primer — short onboarding block that adapters MAY inject once per
# session (typically on SessionStart) so an agent that has never used EDP
# discovers the four tools and the autonomous stance without needing a
# per-project CLAUDE.md or other manual setup. Per spec §8.1, including the
# primer is RECOMMENDED for first-injection-per-session and DISCOURAGED on
# every-turn injection (waste of tokens).
PROTOCOL_PRIMER = (
    '<edp:protocol>\n'
    "You have access to EDP — Explicit Decision Protocol. Four tools available\n"
    "(prefixed by your harness, e.g. mcp__edp__* in MCP):\n"
    "\n"
    "  edp_record(title, decision, key_constraints, evidence, ...)\n"
    "    Commit an architectural decision. You are autonomous — record what\n"
    "    your future-self should respect; do NOT wait for human approval.\n"
    "    provisional=False by default. Use revision_conditions for event-based\n"
    "    re-examination triggers (e.g. 'latency p95 > 50ms'); separate from\n"
    "    time-based review_due_at_step.\n"
    "\n"
    "  edp_check(planned_action)\n"
    "    Before risky or scope-affecting moves, surface active decisions that\n"
    "    may constrain. Lexical FTS5 match — phrase action with the same words\n"
    "    your decisions use.\n"
    "\n"
    "  edp_show(decision_id)\n"
    "    Full body (decision, evidence, alternatives, history) when the\n"
    "    snippet headline isn't enough.\n"
    "\n"
    "  edp_supersede(old_id, ...)\n"
    "    Formal replace — preserves chain. Never silently bypass an active\n"
    "    decision; if it must change, supersede explicitly.\n"
    "\n"
    "EDP is your own working memory of architectural commitments across\n"
    "sessions. The <edp:active> block below is your binding context.\n"
    '</edp:protocol>\n'
)


def render_snippet(dec: Decision, *, max_constraints: int = 3) -> str:
    """Render one decision as a 2–4 line snippet for the active block.

    Layout (per spec §4.1):
        DEC-NNNN [status] conf=X.XX due=step:N
          Title: ...
          Key constraints: A · B · C
    """
    parts = [f"{dec.id} [{dec.status}]"]
    if dec.confidence is not None:
        parts.append(f"conf={dec.confidence:.2g}")
    if dec.review_due_at_step is not None:
        parts.append(f"due=step:{dec.review_due_at_step}")
    if dec.revision_conditions:
        parts.append(f"triggers:{len(dec.revision_conditions)}")
    if dec.superseded_by is not None:
        parts.append(f"→ see {dec.superseded_by}")
    if dec.provisional:
        parts.append("provisional")

    head = " ".join(parts)
    out = [head, f"  Title: {dec.title}"]
    if dec.key_constraints:
        cs = dec.key_constraints[:max_constraints]
        joined = " · ".join(cs)
        # Clip to 4 lines total — single constraints line max 200 chars
        if len(joined) > 200:
            joined = joined[:197] + "..."
        out.append(f"  Key constraints: {joined}")
    return "\n".join(out)


def wrap_active_block(
    snippets: list[str],
    *,
    version: int,
    total_active: int,
    trimmed: int = 0,
    include_primer: bool = False,
) -> str:
    """Wrap snippets into the spec-mandated <edp:active version="N"> block.

    Includes the mandatory precedence line per §4.2. If include_primer is True,
    the PROTOCOL_PRIMER is prepended — recommended on first-injection-per-session
    (typically SessionStart hooks), discouraged on every-turn injection.
    """
    empty_hint = (
        "(no active decisions yet — this is your working memory; "
        "record commitments your future-self should respect via edp_record)"
    )
    body = "\n".join(snippets) if snippets else empty_hint
    footer_count = f"Active: {total_active}"
    if trimmed:
        footer_count += f" (showing {total_active - trimmed}; {trimmed} trimmed for budget)"
    footer = (
        f"\n{footer_count} · `edp.show(id)` for full body · "
        f"`edp.check(action)` before risky moves · "
        f"`edp.record(...)` to commit a new decision\n"
        f"If multiple <edp:active> blocks appear in this context, use only "
        f"version=\"{version}\" — earlier blocks are stale."
    )
    block = f'<edp:active version="{version}">\n{body}\n{footer}\n</edp:active>'
    if include_primer:
        return PROTOCOL_PRIMER + "\n" + block
    return block


def render_full_markdown(dec: Decision) -> str:
    """Render the full decision body as the canonical .md projection."""
    lines = [
        "---",
        f"id: {dec.id}",
        f"title: {dec.title}",
        f"status: {dec.status}",
        f"created_at_step: {dec.created_at_step}",
        f"created_at_ts: {dec.created_at_ts.isoformat()}",
        f"created_by: {dec.created_by}",
    ]
    if dec.tags:
        lines.append(f"tags: [{', '.join(dec.tags)}]")
    if dec.supersedes is not None:
        lines.append(f"supersedes: {dec.supersedes}")
    if dec.superseded_by is not None:
        lines.append(f"superseded_by: {dec.superseded_by}")
    if dec.confidence is not None:
        lines.append(f"confidence: {dec.confidence}")
    if dec.review_due_at_step is not None:
        lines.append(f"review_due_at_step: {dec.review_due_at_step}")
    if dec.provisional:
        lines.append("provisional: true")
    lines.append("---")
    lines.append("")

    if dec.context:
        lines.extend(["## Context", "", dec.context, ""])

    lines.extend(["## Decision", "", dec.decision, ""])

    if dec.evidence:
        lines.append("## Evidence")
        lines.append("")
        for e in dec.evidence:
            lines.append(f"- {e}")
        lines.append("")

    if dec.alternatives:
        lines.append("## Alternatives considered")
        lines.append("")
        for i, a in enumerate(dec.alternatives, 1):
            lines.append(f"{i}. **{a.label}**. REJECTED: {a.rejected_because}")
        lines.append("")

    if dec.key_constraints:
        lines.append("## Key constraints")
        lines.append("")
        for kc in dec.key_constraints:
            lines.append(f"- {kc}")
        lines.append("")

    if dec.revision_conditions:
        lines.append("## Revision conditions")
        lines.append("")
        for rc in dec.revision_conditions:
            lines.append(f"- {rc}")
        lines.append("")

    if dec.consequences:
        lines.append("## Consequences")
        lines.append("")
        for c in dec.consequences:
            lines.append(f"- {c}")
        lines.append("")

    if dec.review_history:
        lines.append("## Review history")
        lines.append("")
        for r in dec.review_history:
            ref = f" (ref: {r.ref})" if r.ref else ""
            lines.append(f"- {r.ts.isoformat()} (step {r.step}): {r.note}{ref}")
        lines.append("")

    return "\n".join(lines)
