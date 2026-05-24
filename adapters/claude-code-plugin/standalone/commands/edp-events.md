---
description: Read recent entries from the EDP append-only event log (audit trail).
argument-hint: [--decision DEC-NNNN | --limit N]
---

Use Bash to call the EDP CLI:

```bash
edp events --limit 20                     # last 20 events
edp events --decision DEC-NNNN --limit 50 # all events for one decision
```

Use this when:
- The user asks "who recorded what when?" — answer from the audit log, not memory.
- A decision behaves unexpectedly and you need to trace the supersede chain.
- A `[provisional]` record needs review and you want to see when it was written and by whom.

Summarise the events newest-first, grouping by `decision_id` if helpful.
