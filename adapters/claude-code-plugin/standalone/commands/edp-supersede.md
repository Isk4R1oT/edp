---
description: Formally replace an active EDP decision with a new one (preserves the chain).
argument-hint: <DEC-NNNN to supersede>
---

The user wants to supersede `$ARGUMENTS` with an updated decision. Use the `mcp__edp__edp_supersede` tool.

Workflow:
1. First call `mcp__edp__edp_show` on the old id to surface the current decision, its key_constraints, and rationale — confirm with the user that this is the right target.
2. Collect the new decision contents from the user (same fields as `/edp-record`: title, decision, key_constraints, evidence, confidence).
3. The new record's `key_constraints` should make explicit what changed vs the old constraints, and the `decision` body should open with "Superseding DEC-NNNN: ..." plus the rationale for the change.
4. Call `mcp__edp__edp_supersede` with `old_id=$ARGUMENTS` plus the new fields.
5. Confirm the new id back to the user and remind them the supersede chain (old `[superseded]` → new `[active]`) will be visible in the next turn's active block.

Never use this as a way to bypass a decision the user wants to ignore for one turn. If the user only wants a one-off exception, push back and ask whether the rule should truly change.
