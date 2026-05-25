#!/usr/bin/env python3
"""Back-compat shim for `.claude/settings.json` entries pointing at this file.

New installations should use `python -m edp.hook` directly (or simply run
`edp claude-code install` which writes a correct `settings.json` for you).
This shim is kept so existing settings.json files that reference an absolute
path to this script keep working after the hook moved into the `edp` package
in v0.1.3.
"""

from __future__ import annotations

import sys

try:
    from edp.hook import main
except ImportError:
    # edp not installed in this interpreter — silent fail-soft, same as the
    # original hook's contract: never break the user's Claude Code session.
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main())
