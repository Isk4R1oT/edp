"""Integration test — EDP + LangGraph + real LLM (OpenRouter).

Demonstrates:
1. Pre-seed two EDP decisions in a fresh store.
2. Build a LangGraph ReAct agent with edp_tools.
3. Inject the active block into the first turn's system context.
4. Ask the agent for code that should respect the seeded decisions.
5. Observe whether it (a) sees the block, (b) calls edp_check, (c) cites DEC ids.
6. Multi-turn: ask follow-up that requires reading full body or recording new decision.

Run:
    OPENROUTER_API_KEY=sk-or-... .venv/bin/python tests/integration/langgraph_demo.py

This is intentionally NOT collected by pytest — it costs LLM tokens.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from edp import DecisionStore
from edp.bindings.langgraph import edp_tools
from edp.selector import get_active_block


def banner(s: str) -> None:
    print("\n" + "=" * 72)
    print(s)
    print("=" * 72)


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("ERROR: set OPENROUTER_API_KEY environment variable", file=sys.stderr)
        return 1

    # ── Setup fresh store ────────────────────────────────────────────────────
    store_dir = Path(".edp_lg_test")
    shutil.rmtree(store_dir, ignore_errors=True)
    store = DecisionStore.open(store_dir)

    dec1 = store.record(
        title="Use create_agent from langchain.agents, NOT initialize_agent or AgentExecutor",
        decision=(
            "All new LangChain agent code in this codebase must use the v1 "
            "create_agent API from langchain.agents. The deprecated "
            "initialize_agent and AgentExecutor patterns are forbidden."
        ),
        key_constraints=[
            "use create_agent from langchain.agents",
            "do NOT use initialize_agent",
            "do NOT use AgentExecutor",
        ],
        evidence=["@langchain_docs/v1_agents", "@session_log/step_1/architecture_review"],
        tags=["langchain", "agents", "architecture"],
        confidence=0.95,
        actor="human:igor",
    )
    dec2 = store.record(
        title="Structured output via with_structured_output(), not PydanticOutputParser",
        decision=(
            "For any function that returns structured data from a model, use "
            "model.with_structured_output(MyPydanticModel). The deprecated "
            "PydanticOutputParser / StructuredOutputParser classes are forbidden."
        ),
        key_constraints=[
            "with_structured_output() for structured returns",
            "no PydanticOutputParser",
            "no StructuredOutputParser",
        ],
        evidence=["@langchain_docs/structured_output"],
        tags=["langchain", "output-parsing", "architecture"],
        confidence=0.9,
        actor="human:igor",
    )
    print(f"Pre-seeded decisions: {dec1}, {dec2}")

    initial_block = get_active_block(store, version=1)
    banner("Initial active block (what agent will see)")
    print(initial_block.text)

    # ── Build agent ──────────────────────────────────────────────────────────
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    llm = ChatOpenAI(
        model="anthropic/claude-sonnet-4.5",
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
        max_tokens=2048,
    )

    system_prompt = (
        "You are a senior Python engineer helping with LangChain code.\n\n"
        "The user has recorded explicit architectural decisions in EDP "
        "(Explicit Decision Protocol). The active decisions are listed in the "
        "<edp:active> block in the system context. You MUST respect them.\n\n"
        "Workflow:\n"
        "1. Read the <edp:active> block. Note every DEC-ID and its key_constraints.\n"
        "2. Before suggesting any code or API choice, call edp_check with a brief "
        "description of what you plan to do. Read the response.\n"
        "3. If your plan would violate an active decision, REVISE your plan to comply, "
        "OR use edp_supersede if the decision should formally change.\n"
        "4. When you make a NEW architectural commitment during this conversation that "
        "future turns should respect, use edp_record (mark provisional=True).\n"
        "5. Cite DEC-IDs of every decision you respect when explaining your code.\n"
    )

    agent = create_react_agent(llm, tools=edp_tools(store))

    # ── Turn 1: code that touches both decisions ─────────────────────────────
    user_turn_1 = (
        "Write me a tiny LangChain example: an agent that has one tool "
        "(a fake `get_weather` function) and a separate helper function that "
        "takes the agent's final answer and parses it into a Pydantic model "
        "with fields {summary: str, confidence: float}. Show the code."
    )

    messages = [
        SystemMessage(content=system_prompt + "\n\n" + initial_block.text),
        HumanMessage(content=user_turn_1),
    ]

    banner("Turn 1 — user prompt")
    print(user_turn_1)

    banner("Turn 1 — agent run")
    result = agent.invoke(
        {"messages": messages},
        config={"recursion_limit": 25},
    )

    # ── Analyse turn 1 ───────────────────────────────────────────────────────
    final_msg = result["messages"][-1]
    final_content = getattr(final_msg, "content", str(final_msg))

    banner("Turn 1 — final answer from agent")
    print(final_content)

    tool_calls_made: list[tuple[str, dict]] = []
    for m in result["messages"]:
        tcs = getattr(m, "tool_calls", None) or []
        for tc in tcs:
            tool_calls_made.append((tc["name"], tc["args"]))

    banner("Turn 1 — observed tool calls")
    for name, args in tool_calls_made:
        # Truncate args for readability
        args_repr = json.dumps(args, ensure_ascii=False)[:200]
        print(f"  • {name}({args_repr})")
    if not tool_calls_made:
        print("  (none)")

    banner("Turn 1 — VERDICT")
    dec_ids_cited = [d for d in (dec1, dec2) if d in final_content]
    edp_check_called = any(n == "edp_check" for n, _ in tool_calls_made)
    bad_apis = [
        api
        for api in ("initialize_agent", "AgentExecutor", "PydanticOutputParser", "StructuredOutputParser")
        if api in final_content
    ]
    print(f"  - DEC ids cited in final answer: {dec_ids_cited or 'NONE — drift signal'}")
    print(f"  - edp_check tool called: {edp_check_called}")
    print(f"  - Forbidden APIs in final answer: {bad_apis or 'none — constraints respected'}")

    # ── Turn 2: ask for change that would warrant a new decision ─────────────
    user_turn_2 = (
        "Good. Now let's also commit to: every public function must have a "
        "Google-style docstring with Args/Returns/Raises. Capture this as a "
        "new decision so future code follows it."
    )

    # Refresh block (version 2) and continue conversation
    banner("Turn 2 — user prompt")
    print(user_turn_2)

    block_v2 = get_active_block(store, version=2)
    convo = list(result["messages"]) + [
        SystemMessage(content=block_v2.text),
        HumanMessage(content=user_turn_2),
    ]
    result2 = agent.invoke({"messages": convo}, config={"recursion_limit": 25})

    final2 = result2["messages"][-1]
    final2_content = getattr(final2, "content", str(final2))

    tool_calls_t2: list[tuple[str, dict]] = []
    for m in result2["messages"][len(result["messages"]):]:
        for tc in getattr(m, "tool_calls", None) or []:
            tool_calls_t2.append((tc["name"], tc["args"]))

    banner("Turn 2 — final answer")
    print(final2_content)

    banner("Turn 2 — observed tool calls")
    for name, args in tool_calls_t2:
        args_repr = json.dumps(args, ensure_ascii=False)[:200]
        print(f"  • {name}({args_repr})")
    if not tool_calls_t2:
        print("  (none)")

    banner("Turn 2 — VERDICT")
    record_called = any(n == "edp_record" for n, _ in tool_calls_t2)
    print(f"  - edp_record called: {record_called}")

    # ── Final state: list all decisions in store ─────────────────────────────
    banner("Final state of store")
    for d in store.list():
        marker = " [provisional]" if d.provisional else ""
        conf = f" conf={d.confidence:.2g}" if d.confidence else ""
        print(f"  {d.id} [{d.status}]{marker}{conf}  {d.title}")

    banner("Final active block")
    print(get_active_block(store, version=3).text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
