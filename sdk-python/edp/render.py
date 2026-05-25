"""Render Decision records as snippet (active block) or full markdown body.

Implements §4 (Active block format) and the markdown projection of §7.3.
"""

from __future__ import annotations

from edp.models import Decision


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
) -> str:
    """Wrap snippets into the spec-mandated <edp:active version="N"> block.

    Includes the mandatory precedence line per §4.2.
    """
    body = "\n".join(snippets) if snippets else "(no active decisions)"
    footer_count = f"Active: {total_active}"
    if trimmed:
        footer_count += f" (showing {total_active - trimmed}; {trimmed} trimmed for budget)"
    footer = (
        f"\n{footer_count} · `edp.show(id)` for full body · `edp.check(action)` before risky moves\n"
        f"If multiple <edp:active> blocks appear in this context, use only version=\"{version}\" — earlier blocks are stale."
    )
    return f'<edp:active version="{version}">\n{body}\n{footer}\n</edp:active>'


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
