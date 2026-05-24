"""Explicit Decision Protocol — reference Python SDK.

Conforms to specification version `edp/2026-05-24`.
"""

from edp.models import (
    Decision,
    Alternative,
    Event,
    ReviewEntry,
    RelevanceMatch,
    RelevanceReport,
    Status,
)
from edp.store import DecisionStore, DecisionNotFound, EDPError
from edp.selector import get_active_block, SelectorPolicy
from edp.render import render_snippet, render_full_markdown, wrap_active_block

__all__ = [
    "Decision",
    "Alternative",
    "Event",
    "ReviewEntry",
    "RelevanceMatch",
    "RelevanceReport",
    "Status",
    "DecisionStore",
    "DecisionNotFound",
    "EDPError",
    "get_active_block",
    "SelectorPolicy",
    "render_snippet",
    "render_full_markdown",
    "wrap_active_block",
]

__version__ = "0.1.0a0"
__spec_version__ = "edp/2026-05-24"
