---
description: Before a risky action, surface active EDP decisions that may apply.
argument-hint: <one-line description of the action you're about to take>
---

Use the `mcp__edp__edp_check` tool with `planned_action="$ARGUMENTS"` to see which active decisions might constrain this action.

The check is **lexical** (SQLite FTS5 over titles, decisions, and key_constraints) — not semantic. Phrase the planned action with the same vocabulary used in the project's decisions.

After the tool returns:
- If `related` is empty, tell the user "no active decisions match this action — clear to proceed".
- If non-empty, list each match with its id, relevance, and the `why` rationale. Then assess whether the planned action genuinely conflicts.
- If a real conflict exists, suggest the formal path: either revise the plan to comply, or supersede the decision via `/edp-supersede` if it should change.
- Never silently bypass a hit.
