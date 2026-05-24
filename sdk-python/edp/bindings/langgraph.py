"""LangGraph / LangChain binding for EDP.

Provides:
- `edp_tools(store)` — returns the four core tools as LangChain `Tool` objects
- `edp_before_model(store)` — middleware factory for `@before_model` hook

Per spec §8.2: this middleware MUST be registered BEFORE LangChain's
SummarizationMiddleware so the injected EDP block survives summarization.

Requires: langchain >= 1.0, langgraph >= 0.2.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool

from edp.selector import SelectorPolicy, get_active_block
from edp.store import DecisionStore


def edp_tools(store: DecisionStore) -> list[Any]:
    """Return the four core EDP tools as LangChain Tool objects.

    Pass to a LangGraph agent via `tools=[*edp_tools(store), *your_other_tools]`.
    """

    @tool
    def edp_show(decision_id: str) -> dict:
        """Get the full body of one EDP decision by id (DEC-NNNN).

        Use this when the snippet in the active block is not enough and you need
        the reasoning, evidence, alternatives, or full history of a decision.
        """
        return store.show(decision_id).model_dump(mode="json")

    @tool
    def edp_check(planned_action: str) -> dict:
        """Return EDP active decisions relevant to a planned action.

        Call this BEFORE risky or scope-affecting actions to see whether any
        active decision constrains what you are about to do. Soft check — does
        not block; you decide what to do with the returned matches.
        """
        return store.check(planned_action).model_dump(mode="json")

    @tool
    def edp_record(
        title: str,
        decision: str,
        key_constraints: list[str],
        evidence: list[str],
        confidence: float = 0.7,
        tags: Optional[list[str]] = None,
        provisional: bool = True,
    ) -> str:
        """Record a new EDP decision; returns the assigned DEC-NNNN id.

        Mark provisional=True (default) so a human can confirm before the
        decision becomes binding on future work.
        """
        return store.record(
            title=title,
            decision=decision,
            key_constraints=key_constraints,
            evidence=evidence,
            tags=tags or [],
            confidence=confidence,
            actor="agent:langgraph",
            provisional=provisional,
        )

    @tool
    def edp_supersede(
        old_id: str,
        title: str,
        decision: str,
        key_constraints: list[str],
        evidence: list[str],
        confidence: float = 0.7,
    ) -> str:
        """Replace an existing EDP decision with a new one; chain is preserved."""
        return store.supersede(
            old_id,
            title=title,
            decision=decision,
            key_constraints=key_constraints,
            evidence=evidence,
            confidence=confidence,
            actor="agent:langgraph",
        )

    return [edp_show, edp_check, edp_record, edp_supersede]


def edp_before_model(
    store: DecisionStore,
    *,
    policy: Optional[SelectorPolicy] = None,
    tags: Optional[list[str]] = None,
) -> Callable:
    """Build a `@before_model` middleware that prepends the EDP active block.

    Usage in LangGraph v1.x:

        from langchain.agents import create_agent
        agent = create_agent(
            model=...,
            tools=[*edp_tools(store), *other_tools],
            middleware=[edp_before_model(store)],
        )

    Per spec §8.2: register this middleware BEFORE SummarizationMiddleware.
    """
    version_state = {"n": 0}

    def middleware(state: dict, *args, **kwargs) -> dict:
        version_state["n"] += 1
        block = get_active_block(
            store,
            version=version_state["n"],
            context_tags=tags,
            policy=policy,
        )
        msgs = list(state.get("messages") or [])
        msgs.insert(0, SystemMessage(content=block.text))
        return {"messages": msgs}

    return middleware


def inject_into_messages(
    store: DecisionStore,
    messages: list,
    *,
    version: int = 1,
    tags: Optional[list[str]] = None,
    policy: Optional[SelectorPolicy] = None,
) -> list:
    """Lightweight alternative: prepend the active block to any message list.

    Useful when you do not want middleware semantics — just want to inject
    decisions into a one-shot prompt construction.
    """
    block = get_active_block(store, version=version, context_tags=tags, policy=policy)
    return [SystemMessage(content=block.text), *messages]
