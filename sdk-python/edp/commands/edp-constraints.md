---
description: List or manage EDP constraints (non-negotiable axioms — risk limits, safety rules, compliance).
argument-hint: [add --rule "..." | list | show CON-NNNN | remove CON-NNNN | confirm CON-NNNN]
---

Constraints are **non-negotiable axioms** — distinct from decisions (DEC-*).
Unlike decisions, constraints have no supersede chain, no revision_conditions,
no alternatives. They just ARE. Use for things like "max leverage 10x",
"every order must have a stop-loss", or "PII must never leave the EU region".

```bash
edp constraint list                       # show all
edp constraint add --rule "Max leverage 10x" --tag risk
edp constraint show CON-0001
edp constraint remove CON-0001 --reason "policy change 2026-Q2"
edp constraint confirm CON-0002           # promote provisional → confirmed
```

After listing, briefly note how many constraints are active and which tags
they cover. If the user is about to take an action that may interact with a
constraint, point at the relevant CON-* explicitly. The agent CANNOT
supersede constraints — only the operator can `remove` and re-`add`.

Authorship modes (set via `EDP_CONSTRAINT_MODE`):

  - `human_only` (default) — only the human can add constraints; the agent's
    MCP `edp_add_constraint` tool is hidden entirely.
  - `agent_auto`           — agent can add directly via MCP.
  - `agent_provisional`    — agent adds with `provisional=true`; the human
    confirms via `edp constraint confirm CON-NNNN`.
