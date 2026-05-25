---
description: Record a new EDP decision (will show in the active block from next turn).
argument-hint: <title — short imperative statement>
---

Use the `mcp__edp__edp_record` tool to capture a new decision in the project's EDP store.

Inputs to collect from the user (ask if not in `$ARGUMENTS`):

- **title** (≤120 chars, imperative): "$ARGUMENTS" is the seed; expand to a clean one-liner.
- **decision**: full markdown statement (one decision per record — if there are two, record them separately).
- **key_constraints**: 1–4 short imperative bullets (≤140 chars each), each one being something a future agent could match a planned action against (e.g. `"no XML serialisation in new endpoints"`).
- **evidence**: stable handles like `@session_log/step_N/...`, `@artifacts/path/file.py:42`, `@incidents/2026-Q1/...` — do NOT use free text.
- **confidence**: number in `[0.0, 1.0]`. Be honest — `0.99` on every decision is a calibration failure.
- **revision_conditions** (optional but encouraged): natural-language event triggers that would invalidate this decision. e.g. *"pgvector recall drops below 0.9 vs baseline"*, *"user explicitly mentions SMB segment in a later turn"*. Different from `review_due_at_step` (time-based). Use when the right answer depends on observable state, not the calendar.
- **review_due_at_step** (optional): step at which this should be re-confirmed. Defaults: business decisions +100, technical +50, tactical +20.
- **provisional**: default `false`. Set `true` ONLY if your confidence is below ~0.5 AND superseding an existing decision is not the right move. EDP is the agent's own working memory — by default the agent is committing, not proposing.

Before calling the tool, decide whether this is decision-worthy per SPEC §3.7 — at least two of: multi-turn consequence, constraint-shaped, hard to re-derive, reversibility-relevant. If none apply, do NOT record; tell the user why.

After recording, confirm the assigned `DEC-NNNN` id back to the user and remind them the snippet will appear in the next turn's active block.
