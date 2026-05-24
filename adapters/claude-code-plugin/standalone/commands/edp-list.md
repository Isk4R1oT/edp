---
description: List EDP decisions in the project store (active by default).
argument-hint: [--all | --status STATUS | --tag TAG]
---

Use the `mcp__edp__edp_show` tool individually for full bodies, or call the CLI through Bash:

```bash
edp list --active        # default: active + revised only
edp list                 # all decisions including superseded/deprecated
edp list --tag TAG       # filter by tag
edp list --status STATUS # filter by status
```

After listing, briefly summarise the distribution (how many active, how many superseded) and offer to `/edp-show` any specific id.

Use the CLI rather than the MCP tool here because the four MCP tools are designed for the per-decision write/read loop, not for bulk listing.
