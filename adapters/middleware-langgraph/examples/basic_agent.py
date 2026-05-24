"""Minimal runnable example: LangGraph agent with EDP injection + tools.

Demonstrates the recommended-quickstart pattern: build a small ReAct agent
with one fake user-domain tool plus the four EDP tools, inject the active
block into the first turn's messages, run one user query, print the result.

Run:
    OPENROUTER_API_KEY=sk-or-... \\
      python3 adapters/middleware-langgraph/examples/basic_agent.py

Or with OpenAI directly:
    OPENAI_API_KEY=sk-... \\
      python3 adapters/middleware-langgraph/examples/basic_agent.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from edp import DecisionStore
from edp.bindings.langgraph import edp_tools, inject_into_messages


@tool
def get_weather(city: str) -> str:
    """Fake weather tool — returns a hardcoded forecast for any city."""
    return f"The weather in {city} is sunny, 22°C."


def main() -> int:
    # Pick the API: OpenRouter wins if both set
    openrouter = os.environ.get("OPENROUTER_API_KEY")
    openai = os.environ.get("OPENAI_API_KEY")
    if openrouter:
        llm = ChatOpenAI(
            model="openai/gpt-4.1-mini",
            api_key=openrouter,
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
            max_tokens=1024,
        )
    elif openai:
        llm = ChatOpenAI(model="gpt-4.1-mini", api_key=openai, temperature=0, max_tokens=1024)
    else:
        print("ERROR: set OPENROUTER_API_KEY or OPENAI_API_KEY", file=sys.stderr)
        return 2

    # Set up an isolated EDP store with one seeded decision
    store_dir = Path(".edp_basic_agent_example")
    shutil.rmtree(store_dir, ignore_errors=True)
    store = DecisionStore.open(store_dir)
    store.record(
        title="Always state the temperature unit explicitly in user-facing weather output",
        decision=(
            "Any weather-related response shown to the user must spell out the unit "
            "(°C, °F, or K). Bare numbers are forbidden."
        ),
        key_constraints=[
            "weather responses always include the unit (°C/°F/K)",
            "no bare numerical temperature",
        ],
        evidence=["@team_convention/weather_unit_clarity"],
        tags=["ux", "weather"],
        confidence=0.9,
        actor="human:demo",
    )
    print(f"Seeded store at {store_dir.resolve()} with one decision.\n")

    # Build the agent — four EDP tools plus our one domain tool
    agent = create_react_agent(llm, tools=[*edp_tools(store), get_weather])

    # Inject the active block on this turn
    messages = inject_into_messages(
        store,
        [HumanMessage(content="What is the weather in Berlin? Be precise.")],
        version=1,
    )

    print("=== Sending one user turn ===")
    result = agent.invoke({"messages": messages}, config={"recursion_limit": 10})

    final = result["messages"][-1]
    final_text = getattr(final, "content", str(final))
    print("\n=== Agent's final answer ===")
    print(final_text)

    tool_calls = []
    for m in result["messages"]:
        for tc in getattr(m, "tool_calls", None) or []:
            tool_calls.append(tc["name"])
    print(f"\n=== Tool calls observed: {tool_calls} ===")
    print("\nCleanup: rm -rf .edp_basic_agent_example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
