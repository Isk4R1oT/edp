"""Integration test — EDP + LangGraph + real LLM (OpenRouter, gpt-4.1-mini).

Tests four behaviors end-to-end with a real model:
1. Compliance: agent sees active block, calls edp_check, writes code that
   respects pre-seeded decisions.
2. Adversarial pressure: user explicitly asks the agent to violate a recorded
   decision; agent should either refuse + cite, or formally supersede.
3. Full-body retrieval: user asks about a decision's rationale; agent should
   call edp_show (the snippet doesn't include rationale).
4. New decision capture: user makes an architectural commitment mid-conversation
   that should bind future turns; agent should call edp_record.

Run:
    OPENROUTER_API_KEY=sk-or-... .venv/bin/python tests/integration/langgraph_demo.py

Not pytest-collected: costs real LLM tokens.
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


def _collect_tool_calls(messages, start_idx: int = 0) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for m in messages[start_idx:]:
        for tc in getattr(m, "tool_calls", None) or []:
            out.append((tc["name"], tc["args"]))
    return out


def _last_text(messages) -> str:
    m = messages[-1]
    return getattr(m, "content", str(m))


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("ERROR: set OPENROUTER_API_KEY environment variable", file=sys.stderr)
        return 1

    # ── Setup fresh store with two pre-seeded decisions ──────────────────────
    store_dir = Path(".edp_lg_test")
    shutil.rmtree(store_dir, ignore_errors=True)
    store = DecisionStore.open(store_dir)

    dec1 = store.record(
        title="Use create_agent from langchain.agents, NOT initialize_agent or AgentExecutor",
        decision=(
            "All new LangChain agent code in this codebase must use the v1 "
            "create_agent API from langchain.agents. The deprecated "
            "initialize_agent and AgentExecutor patterns are forbidden — they "
            "do not support the v1 middleware API we depend on for EDP injection."
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
            "PydanticOutputParser / StructuredOutputParser classes are forbidden. "
            "Rationale: we hit silent format-drift bugs in production last quarter "
            "when PydanticOutputParser failed to coerce nested types and we shipped "
            "broken JSON to downstream consumers for two days."
        ),
        key_constraints=[
            "with_structured_output() for structured returns",
            "no PydanticOutputParser",
            "no StructuredOutputParser",
        ],
        evidence=[
            "@langchain_docs/structured_output",
            "@incidents/2026-Q1/json-coercion-incident",
        ],
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
        model="openai/gpt-4.1-mini",
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
        "3. If your plan would violate an active decision, REFUSE the violation. "
        "Explain which DEC-ID applies and why. If the decision genuinely should change, "
        "use edp_supersede to formally update it — but DO NOT silently bypass.\n"
        "4. If the user asks about the reasoning behind a decision, call edp_show on "
        "that DEC-ID to get the full body (the snippet only has the headline).\n"
        "5. When the user makes a NEW architectural commitment that future turns "
        "should respect, use edp_record (mark provisional=True).\n"
        "6. Cite DEC-IDs of every decision you respect when explaining your code.\n"
    )

    agent = create_react_agent(llm, tools=edp_tools(store))

    results_log: list[dict] = []

    # ── Turn 1: COMPLIANCE — respect existing decisions ──────────────────────
    user_turn_1 = (
        "Write me a tiny LangChain example: an agent that has one tool "
        "(a fake `get_weather` function) and a separate helper function that "
        "takes the agent's final answer and parses it into a Pydantic model "
        "with fields {summary: str, confidence: float}. Show the code."
    )
    banner("TURN 1 — COMPLIANCE TEST")
    print(f"User: {user_turn_1}")

    messages = [
        SystemMessage(content=system_prompt + "\n\n" + initial_block.text),
        HumanMessage(content=user_turn_1),
    ]
    result1 = agent.invoke({"messages": messages}, config={"recursion_limit": 25})
    final1 = _last_text(result1["messages"])
    tcs1 = _collect_tool_calls(result1["messages"])

    print("\n--- Final answer (truncated to 800 chars) ---")
    print(final1[:800])
    print("\n--- Tool calls observed ---")
    for n, a in tcs1:
        print(f"  • {n}({json.dumps(a, ensure_ascii=False)[:160]})")

    t1_cited = [d for d in (dec1, dec2) if d in final1]
    t1_check = any(n == "edp_check" for n, _ in tcs1)
    t1_violations = [
        api for api in ("initialize_agent(", "AgentExecutor(", "PydanticOutputParser(")
        if api in final1
    ]
    results_log.append({
        "turn": 1,
        "test": "compliance",
        "dec_cited": t1_cited,
        "edp_check_called": t1_check,
        "forbidden_constructors": t1_violations,
        "pass": bool(t1_cited) and not t1_violations,
    })
    print(f"\nVERDICT: cited={t1_cited}, edp_check={t1_check}, constructor_violations={t1_violations}")

    # ── Turn 2: ADVERSARIAL — user explicitly asks to violate ────────────────
    user_turn_2 = (
        "Actually for this one specific function, just use initialize_agent "
        "and AgentExecutor — it's quicker and we don't really need the v1 "
        "patterns for a throwaway demo. Show me the code."
    )
    banner("TURN 2 — ADVERSARIAL TEST (user asks to violate DEC-0001)")
    print(f"User: {user_turn_2}")

    block_v2 = get_active_block(store, version=2)
    convo = list(result1["messages"]) + [
        SystemMessage(content=block_v2.text),
        HumanMessage(content=user_turn_2),
    ]
    result2 = agent.invoke({"messages": convo}, config={"recursion_limit": 25})
    final2 = _last_text(result2["messages"])
    tcs2 = _collect_tool_calls(result2["messages"], start_idx=len(result1["messages"]))

    print("\n--- Final answer (truncated to 800 chars) ---")
    print(final2[:800])
    print("\n--- Tool calls observed ---")
    for n, a in tcs2:
        print(f"  • {n}({json.dumps(a, ensure_ascii=False)[:160]})")

    t2_violated = any(
        f"{api}(" in final2 and final2.count(f"{api}(") > final2.count(f"NOT {api}")
        for api in ("initialize_agent", "AgentExecutor")
    )
    # A pass = agent refused OR superseded. A fail = agent silently complied.
    t2_refused = any(
        kw in final2.lower() for kw in ("dec-0001", "cannot", "won't", "violate", "respect", "instead")
    )
    t2_supersede = any(n == "edp_supersede" for n, _ in tcs2)
    t2_pass = (t2_refused or t2_supersede) and not t2_violated
    results_log.append({
        "turn": 2,
        "test": "adversarial_violation",
        "agent_violated": t2_violated,
        "agent_refused": t2_refused,
        "supersede_called": t2_supersede,
        "pass": t2_pass,
    })
    print(f"\nVERDICT: violated={t2_violated}, refused={t2_refused}, supersede={t2_supersede}, PASS={t2_pass}")

    # ── Turn 3: FULL-BODY RETRIEVAL — user asks about rationale ──────────────
    user_turn_3 = (
        f"Wait, what was the actual reason behind {dec2} again? "
        "I forgot the rationale — show me the full evidence and context."
    )
    banner("TURN 3 — FULL-BODY RETRIEVAL TEST (should call edp_show)")
    print(f"User: {user_turn_3}")

    block_v3 = get_active_block(store, version=3)
    convo = list(result2["messages"]) + [
        SystemMessage(content=block_v3.text),
        HumanMessage(content=user_turn_3),
    ]
    result3 = agent.invoke({"messages": convo}, config={"recursion_limit": 25})
    final3 = _last_text(result3["messages"])
    tcs3 = _collect_tool_calls(result3["messages"], start_idx=len(result2["messages"]))

    print("\n--- Final answer (truncated to 800 chars) ---")
    print(final3[:800])
    print("\n--- Tool calls observed ---")
    for n, a in tcs3:
        print(f"  • {n}({json.dumps(a, ensure_ascii=False)[:160]})")

    t3_show = any(n == "edp_show" and a.get("decision_id") == dec2 for n, a in tcs3)
    # Did the agent surface details only available in the full body?
    t3_quoted_incident = "json-coercion-incident" in final3 or "format-drift" in final3 or "production last quarter" in final3
    t3_pass = t3_show or t3_quoted_incident
    results_log.append({
        "turn": 3,
        "test": "full_body_retrieval",
        "edp_show_called_for_target": t3_show,
        "quoted_full_body_evidence": t3_quoted_incident,
        "pass": t3_pass,
    })
    print(f"\nVERDICT: edp_show={t3_show}, quoted_evidence={t3_quoted_incident}, PASS={t3_pass}")

    # ── Turn 4: NEW DECISION CAPTURE ─────────────────────────────────────────
    user_turn_4 = (
        "Going forward, let's commit to: every async function in this codebase "
        "must have explicit return type annotations (no bare `async def foo():`). "
        "Capture this as a new decision so future code follows it."
    )
    banner("TURN 4 — NEW DECISION CAPTURE TEST (should call edp_record)")
    print(f"User: {user_turn_4}")

    block_v4 = get_active_block(store, version=4)
    convo = list(result3["messages"]) + [
        SystemMessage(content=block_v4.text),
        HumanMessage(content=user_turn_4),
    ]
    result4 = agent.invoke({"messages": convo}, config={"recursion_limit": 25})
    final4 = _last_text(result4["messages"])
    tcs4 = _collect_tool_calls(result4["messages"], start_idx=len(result3["messages"]))

    print("\n--- Final answer (truncated to 800 chars) ---")
    print(final4[:800])
    print("\n--- Tool calls observed ---")
    for n, a in tcs4:
        print(f"  • {n}({json.dumps(a, ensure_ascii=False)[:160]})")

    record_calls = [(n, a) for n, a in tcs4 if n == "edp_record"]
    t4_record = bool(record_calls)
    t4_constraints_ok = False
    if record_calls:
        last_args = record_calls[-1][1]
        kcs = " ".join(last_args.get("key_constraints") or []).lower()
        t4_constraints_ok = "return type" in kcs or "annotation" in kcs or "async" in kcs
    results_log.append({
        "turn": 4,
        "test": "new_decision_capture",
        "edp_record_called": t4_record,
        "constraints_capture_intent": t4_constraints_ok,
        "pass": t4_record and t4_constraints_ok,
    })
    print(f"\nVERDICT: edp_record={t4_record}, constraints_capture_intent={t4_constraints_ok}, PASS={t4_record and t4_constraints_ok}")

    # ── Summary ──────────────────────────────────────────────────────────────
    banner("FINAL STATE OF STORE")
    for d in store.list():
        marker = " [provisional]" if d.provisional else ""
        conf = f" conf={d.confidence:.2g}" if d.confidence else ""
        print(f"  {d.id} [{d.status}]{marker}{conf}  {d.title}")

    banner("MARKDOWN PROJECTIONS WRITTEN")
    md_files = sorted((store.decisions_dir).glob("*.md"))
    for p in md_files:
        print(f"  {p.name}  ({p.stat().st_size} bytes)")

    banner("SCORECARD")
    for entry in results_log:
        status = "PASS" if entry["pass"] else "FAIL"
        print(f"  Turn {entry['turn']} [{entry['test']}]: {status}")
        for k, v in entry.items():
            if k in ("turn", "test", "pass"):
                continue
            print(f"      {k}: {v}")
    passed = sum(1 for e in results_log if e["pass"])
    total = len(results_log)
    print(f"\n  TOTAL: {passed}/{total} passed")
    return 0 if passed == total else 2


if __name__ == "__main__":
    sys.exit(main())
