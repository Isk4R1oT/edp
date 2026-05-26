"""Render Decision records as snippet (active block) or full markdown body.

Implements §4 (Active block format) and the markdown projection of §7.3.
"""

from __future__ import annotations

from edp.models import Constraint, Decision


# Protocol primer — short onboarding block that adapters MAY inject once per
# session (typically on SessionStart) so an agent that has never used EDP
# discovers the four tools and the autonomous stance without needing a
# per-project CLAUDE.md or other manual setup. Per spec §8.1, including the
# primer is RECOMMENDED for first-injection-per-session and DISCOURAGED on
# every-turn injection (waste of tokens).
PROTOCOL_PRIMER = (
    '<edp:protocol>\n'
    "You have access to EDP — Explicit Decision Protocol. Tools available\n"
    "(prefixed by your harness, e.g. mcp__edp__* in MCP):\n"
    "\n"
    "Two primitives:\n"
    "  CONSTRAINTS (CON-NNNN) — non-negotiable axioms. Never violate them;\n"
    "    cannot be superseded by you. Risk limits, safety rules, compliance.\n"
    "  DECISIONS (DEC-NNNN)   — revisable architectural choices with rationale.\n"
    "    You may supersede them when conditions change.\n"
    "\n"
    "  edp_record(title, decision, key_constraints, evidence, invariants=[], ...)\n"
    "    Commit an architectural DECISION. You are autonomous — record what\n"
    "    your future-self should respect; do NOT wait for human approval.\n"
    "    provisional=False by default. invariants are machine-checkable\n"
    "    predicates the verifier enforces (e.g. 'all responses MUST be JSON,\n"
    "    not XML'); key_constraints are human-facing constraints shown in\n"
    "    the snippet. Use revision_conditions for event-based re-examination\n"
    "    triggers (e.g. 'latency p95 > 50ms'); separate from time-based\n"
    "    review_due_at_step.\n"
    "\n"
    "  edp_constraints()\n"
    "    List non-negotiable axioms (constraints). Always read first when\n"
    "    your action touches a domain a constraint covers — they are absolute.\n"
    "    The active block shows them at the top, never trimmed.\n"
    "\n"
    "  edp_check(planned_action)\n"
    "    Lexical advisory: surface decisions that may apply to a planned move.\n"
    "    FTS5 keyword match — fast, free, useful for routine pre-action scans.\n"
    "\n"
    "  edp_verify(planned_action)\n"
    "    ADVISORY pre-flight check: a cheap external model reads your planned\n"
    "    action against active CONSTRAINTS and decision invariants, returns\n"
    "    compatible | violated | uncertain. On 'violated' treat as advisory\n"
    "    block — revise plan, or call edp_supersede if the decision should\n"
    "    change (constraints CANNOT be superseded). Stricter than edp_check\n"
    "    (LLM not lexical). Sends planned-action + rules to Anthropic's API;\n"
    "    only call on non-sensitive content.\n"
    "\n"
    "  edp_show(decision_id)\n"
    "    Full body (decision, evidence, alternatives, history) when the\n"
    "    snippet headline isn't enough.\n"
    "\n"
    "  edp_supersede(old_id, ...)\n"
    "    Formal replace for a DECISION — preserves chain. Never silently\n"
    "    bypass an active decision; if it must change, supersede explicitly.\n"
    "    Does NOT apply to constraints (CON-*) — those are axioms; escalate\n"
    "    to the operator if a constraint is wrong.\n"
    "\n"
    "EDP is your own working memory of architectural commitments across\n"
    "sessions. The <edp:active> block below is your binding context. Snippet\n"
    "headline markers: inv:N = N invariants the verifier will check;\n"
    "alts:N = N alternatives previously rejected; risks:N = N consequences\n"
    "to weigh; triggers:N = N revision_conditions you should watch for.\n"
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
    if dec.invariants:
        # v0.2: machine-checkable predicates the verifier consumes; surfacing
        # the count puts the agent on notice that edp_verify is the right
        # pre-action check here, not just edp_check.
        parts.append(f"inv:{len(dec.invariants)}")
    if dec.alternatives:
        # D's R2: previously dropped rationales (rejected alternatives) become
        # visible at the attention sink so the agent does not re-open them.
        parts.append(f"alts:{len(dec.alternatives)}")
    if dec.consequences:
        # Surface as risks:N so the agent knows there's downside-context to
        # fetch via edp_show before acting against this decision.
        parts.append(f"risks:{len(dec.consequences)}")
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


def render_constraint_snippet(con: Constraint) -> str:
    """Render a constraint as a single line for the active block.

    Constraints are axioms, not heuristics: layout intentionally minimal so
    the agent sees the rule itself rather than metadata. Tags shown in
    compact form; provisional ones are marked because they still need human
    confirmation.
    """
    parts = [con.id]
    if con.provisional:
        parts.append("[provisional]")
    head = " ".join(parts)
    tag_suffix = f"  ({', '.join(con.tags[:3])})" if con.tags else ""
    return f"  {head}: {con.rule}{tag_suffix}"


def wrap_active_block(
    snippets: list[str],
    *,
    version: int,
    total_active: int,
    trimmed: int = 0,
    include_primer: bool = False,
    constraint_snippets: list[str] | None = None,
    total_constraints: int = 0,
) -> str:
    """Wrap snippets into the spec-mandated <edp:active version="N"> block.

    Includes the mandatory precedence line per §4.2. If include_primer is True,
    the PROTOCOL_PRIMER is prepended — recommended on first-injection-per-session
    (typically SessionStart hooks), discouraged on every-turn injection.

    v0.3 (§3.8): if constraint_snippets is non-empty, a "Constraints
    (non-negotiable axioms)" section is rendered at the top of the block,
    before the decisions section. Constraints are never trimmed.
    """
    empty_hint = (
        "(no active decisions yet — this is your working memory; "
        "record commitments your future-self should respect via edp_record)"
    )
    sections: list[str] = []
    if constraint_snippets:
        sections.append(
            "Constraints (non-negotiable axioms — violation must be refused):\n"
            + "\n".join(constraint_snippets)
        )
        sections.append("Decisions (revisable via edp_supersede):")
    sections.append("\n".join(snippets) if snippets else empty_hint)
    body = "\n".join(sections)

    footer_count_parts = []
    if total_constraints:
        footer_count_parts.append(f"Constraints: {total_constraints}")
    footer_count_parts.append(f"Active decisions: {total_active}")
    if trimmed:
        footer_count_parts[-1] += (
            f" (showing {total_active - trimmed}; {trimmed} trimmed for budget)"
        )
    footer_count = " · ".join(footer_count_parts)
    footer = (
        f"\n{footer_count} · `edp.show(id)` full body · "
        f"`edp.check(action)` lexical advisory · "
        f"`edp.verify(action)` LLM advisory · "
        f"`edp.record(...)` to commit\n"
        f"If multiple <edp:active> blocks appear in this context, use only "
        f"version=\"{version}\" — earlier blocks are stale."
    )
    block = f'<edp:active version="{version}">\n{body}\n{footer}\n</edp:active>'
    if include_primer:
        return PROTOCOL_PRIMER + "\n" + block
    return block


def render_constraint_markdown(con: Constraint) -> str:
    """Render a constraint as its canonical .md projection.

    Minimal frontmatter (no status, no chain — by design). Body is just the
    rule itself; constraints are axioms, not narratives.
    """
    lines = [
        "---",
        f"id: {con.id}",
        f"created_at_ts: {con.created_at_ts.isoformat()}",
        f"created_by: {con.created_by}",
    ]
    if con.tags:
        lines.append(f"tags: [{', '.join(con.tags)}]")
    if con.provisional:
        lines.append("provisional: true")
    lines.append("---")
    lines.append("")
    lines.append("## Rule")
    lines.append("")
    lines.append(con.rule)
    lines.append("")
    return "\n".join(lines)


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

    if dec.invariants:
        lines.append("## Invariants")
        lines.append("")
        lines.append("> Machine-checkable predicates the verifier enforces before each action.")
        lines.append("> Each MUST be assertable (per spec §3.6 v0.2).")
        lines.append("")
        for i, inv in enumerate(dec.invariants, 1):
            lines.append(f"- INV-{i}: {inv}")
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
