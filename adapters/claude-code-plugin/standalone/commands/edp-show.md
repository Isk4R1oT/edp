---
description: Fetch the full body of one EDP decision by id (when the snippet isn't enough).
argument-hint: DEC-NNNN
---

Use the `mcp__edp__edp_show` tool to pull the full body of decision `$ARGUMENTS`.

When the user asks "what was the rationale behind DEC-…" or "show me the full evidence for X", the snippet block in context only carries the title and key_constraints — full reasoning, alternatives, evidence handles, and review history live in the full body.

After the tool returns:
- Summarise the rationale faithfully — quote the relevant `evidence` handles by name.
- If the decision has a `superseded_by` field, mention the successor id too.
- Do not paraphrase invariants; quote `key_constraints` verbatim so the user reads the exact wording.
