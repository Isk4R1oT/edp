"""Active-block builder.

Implements §4.3 selector contract. No semantic search in v0.1: tag + recency +
status + (on-demand) FTS only. Trim policy preserves key_constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from edp.models import Decision
from edp.render import render_snippet, wrap_active_block
from edp.store import DecisionStore


# Conservative tokens-per-char ratio. 4 chars ≈ 1 token for English; we are slightly
# pessimistic (3.5) so we under-fill the budget rather than overflow it.
_CHARS_PER_TOKEN = 3.5


@dataclass
class SelectorPolicy:
    token_budget: int = 2000
    max_constraints_per_snippet: int = 3
    include_referenced_history: bool = True
    show_provisional: bool = True


@dataclass
class ActiveBlockResult:
    text: str
    version: int
    total_active: int
    included: int
    trimmed: int
    decisions: list[Decision] = field(default_factory=list)


def get_active_block(
    store: DecisionStore,
    *,
    version: int = 1,
    context_tags: Optional[list[str]] = None,
    policy: Optional[SelectorPolicy] = None,
) -> ActiveBlockResult:
    """Build the `<edp:active>` block for injection.

    Selection policy (default, per spec §4.3):
        1. All `active` (and `revised`) decisions whose tags intersect context_tags,
           OR all of them if no context_tags.
        2. If a `superseded`/`revised` decision is referenced (via supersedes) by an
           included active record, include it too so the agent sees the chain.
        3. Sort by recency desc, then confidence desc.
        4. Trim from the bottom if over token budget.

    Returns ActiveBlockResult with the rendered text and counts.
    """
    pol = policy or SelectorPolicy()
    all_active = store.list_active(include_provisional=pol.show_provisional)
    total_active = len(all_active)

    # Step 1 — tag filter
    if context_tags:
        ctx_set = set(context_tags)
        primary = [d for d in all_active if ctx_set.intersection(d.tags)]
    else:
        primary = list(all_active)

    # Step 2 — pull in referenced superseded/revised records
    extras: list[Decision] = []
    if pol.include_referenced_history:
        referenced_ids: set[str] = set()
        for d in primary:
            if d.supersedes:
                referenced_ids.add(d.supersedes)
        for ref_id in referenced_ids:
            try:
                ref_dec = store.show(ref_id)
                if ref_dec.status in ("superseded", "revised", "deprecated"):
                    extras.append(ref_dec)
            except Exception:
                continue

    # Step 3 — order: pinned (n/a in v0.1) > recency desc > confidence desc
    def _sort_key(d: Decision) -> tuple:
        return (-d.created_at_ts.timestamp(), -(d.confidence or 0.0))

    primary.sort(key=_sort_key)
    extras.sort(key=_sort_key)
    ordered = primary + extras

    # Step 4 — token budget trim
    snippets: list[str] = []
    chars_so_far = 0
    char_budget = int(pol.token_budget * _CHARS_PER_TOKEN)
    included: list[Decision] = []
    for d in ordered:
        snip = render_snippet(d, max_constraints=pol.max_constraints_per_snippet)
        if chars_so_far + len(snip) > char_budget and snippets:
            break
        snippets.append(snip)
        included.append(d)
        chars_so_far += len(snip) + 1  # +1 for newline

    trimmed = len(ordered) - len(included)
    text = wrap_active_block(
        snippets,
        version=version,
        total_active=total_active,
        trimmed=trimmed,
    )
    return ActiveBlockResult(
        text=text,
        version=version,
        total_active=total_active,
        included=len(included),
        trimmed=trimmed,
        decisions=included,
    )
