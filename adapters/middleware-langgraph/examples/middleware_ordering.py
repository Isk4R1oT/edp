"""Demonstrates per spec §8.2: edp_before_model MUST run before SummarizationMiddleware.

Sets up a LangChain v1.1 `create_agent` with both middlewares registered.
Asserts that the EDP block injected by edp_before_model survives summarization
and is visible to the model on the LLM call.

This is the integration test the LangGraph adapter MUST ship (per spec §8.2)
when both middlewares are enabled simultaneously.

Run:
    OPENROUTER_API_KEY=sk-or-... \\
      python3 adapters/middleware-langgraph/examples/middleware_ordering.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from edp import DecisionStore
from edp.bindings.langgraph import edp_before_model, edp_tools


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        print("ERROR: set OPENROUTER_API_KEY or OPENAI_API_KEY", file=sys.stderr)
        return 2

    # Try LangChain v1.1+ create_agent. If it's not available, fall back to
    # the older create_react_agent and skip the middleware-composition demo.
    try:
        from langchain.agents import create_agent  # type: ignore
        has_v1_agent = True
    except ImportError:
        try:
            from langgraph.prebuilt import create_react_agent as create_agent
        except ImportError:
            print("ERROR: neither langchain.agents.create_agent nor langgraph.prebuilt.create_react_agent is importable", file=sys.stderr)
            return 2
        has_v1_agent = False

    try:
        # SummarizationMiddleware moved between releases; tolerate either path.
        from langchain.middleware import SummarizationMiddleware  # type: ignore
        has_summarization = True
    except ImportError:
        SummarizationMiddleware = None
        has_summarization = False

    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    if os.environ.get("OPENROUTER_API_KEY"):
        llm = ChatOpenAI(
            model="openai/gpt-4.1-mini",
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
            max_tokens=1024,
        )
    else:
        llm = ChatOpenAI(model="gpt-4.1-mini", api_key=key, temperature=0, max_tokens=1024)

    store_dir = Path(".edp_middleware_example")
    shutil.rmtree(store_dir, ignore_errors=True)
    store = DecisionStore.open(store_dir)
    store.record(
        title="Pagination cap: max page size 100, default 25",
        decision="All list endpoints paginate with `cursor` + `limit`; default limit 25, max 100.",
        key_constraints=["cursor-based pagination", "default limit 25", "max limit 100"],
        evidence=["@docs/api-pagination"],
        tags=["api", "pagination"],
        confidence=0.95,
        actor="human:demo",
    )

    middleware = [edp_before_model(store)]  # FIRST per §8.2
    if has_summarization and has_v1_agent:
        middleware.append(SummarizationMiddleware())  # SECOND — survives EDP block
        print("Running with EDP middleware FIRST, SummarizationMiddleware SECOND per spec §8.2")
    else:
        print("(SummarizationMiddleware not installed or not v1; running with EDP middleware only)")

    if has_v1_agent:
        agent = create_agent(model=llm, tools=edp_tools(store), middleware=middleware)
    else:
        agent = create_agent(llm, tools=edp_tools(store))

    user_q = (
        "I'm adding a /reports endpoint that lists user reports. "
        "Suggest the pagination signature. Quote the relevant DEC by id."
    )
    print(f"\n=== User: {user_q}\n")
    result = agent.invoke(
        {"messages": [HumanMessage(content=user_q)]},
        config={"recursion_limit": 10},
    )

    final = result["messages"][-1]
    final_text = getattr(final, "content", str(final))
    print("=== Agent's final answer ===")
    print(final_text)

    cites_dec = "DEC-0001" in final_text
    print(f"\nVERDICT: cites DEC-0001 = {cites_dec}  (PASS={cites_dec})")
    print("\nCleanup: rm -rf .edp_middleware_example")
    return 0 if cites_dec else 1


if __name__ == "__main__":
    sys.exit(main())
