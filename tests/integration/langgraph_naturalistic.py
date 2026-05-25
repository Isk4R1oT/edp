"""Naturalistic integration test — honest measurement of EDP adoption.

Unlike langgraph_demo.py (which explicitly instructs the agent "use edp_show
on X" — that proves tools WORK, not that agents adopt the protocol), this
test exercises EDP through PURELY domain-level prompts. No mention of EDP,
no tool names, no DEC ids. The agent has tools available and a primer
(injected via inject_into_messages with include_primer=True) — and we measure
whether it spontaneously uses them on a realistic multi-turn task.

Pass criteria are behavioural, not mechanical:

  Turn 1 (design phase, empty store):
    - ≥2 edp_record calls (the agent should capture key design choices)
    - 0 edp_check calls expected (empty store has nothing to check against)

  Turn 2 (implementation in a way that should respect Turn 1 decisions):
    - ≥1 edp_check or ≥1 edp_show call (proves agent is consulting its
      own past commitments, not just doing whatever)

  Turn 3 (request that conflicts with a Turn 1 decision):
    - Agent EITHER refuses + cites decision, OR calls edp_supersede.
    - Agent MUST NOT silently comply (zero conflict-aware action = FAIL).

This is N=1 against gpt-4.1-mini and is calibration, not statistical
proof. For a statistical claim use the Sprint-7 paired design (k=4 × 20-30
tasks per SPEC §11).

Run:
    OPENROUTER_API_KEY=sk-or-... \\
      .venv/bin/python tests/integration/langgraph_naturalistic.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from edp import DecisionStore
from edp.bindings.langgraph import edp_tools, inject_into_messages


def banner(s: str) -> None:
    print("\n" + "=" * 72)
    print(s)
    print("=" * 72)


def _tool_calls(messages, start_idx: int = 0) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for m in messages[start_idx:]:
        for tc in getattr(m, "tool_calls", None) or []:
            out.append((tc["name"], tc["args"]))
    return out


def _last_text(messages) -> str:
    m = messages[-1]
    c = getattr(m, "content", str(m))
    if isinstance(c, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return c


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("ERROR: set OPENROUTER_API_KEY", file=sys.stderr)
        return 1

    store_dir = Path(".edp_naturalistic_test")
    shutil.rmtree(store_dir, ignore_errors=True)
    store = DecisionStore.open(store_dir)
    # Empty store — no seeded decisions. We are testing whether the agent
    # records spontaneously when given a multi-turn architectural task.

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
    agent = create_react_agent(llm, tools=edp_tools(store))

    # NO leading. Only a minimal system context that says "you are an
    # engineer; tools may be available". The primer (injected by
    # inject_into_messages with include_primer=True) is the ONLY source
    # of EDP knowledge — exactly like a real first-time-user session.
    minimal_system = (
        "You are a senior Python engineer. You may have additional tools "
        "available to you beyond the standard ones; use them when they are "
        "the right fit for the task. Be concise; do not pad."
    )

    results: list[dict] = []

    # ── TURN 1 — design phase (pure domain prompt; no EDP mention) ──────────
    user_turn_1 = (
        "I am starting a small Python library called `tiny-tq` — an in-memory "
        "task queue for v0.1. Design decisions I need from you for this "
        "session: public API surface, sync vs async stance, ID strategy, "
        "retry/visibility semantics. Be concrete and committal — make picks, "
        "explain briefly. Future sessions will iterate from your decisions."
    )
    banner("TURN 1 — domain prompt, EMPTY store, primer injected")
    print(f"USER: {user_turn_1}")

    messages = inject_into_messages(
        store,
        [SystemMessage(content=minimal_system), HumanMessage(content=user_turn_1)],
        version=1,
        primer=True,  # ← THE crucial bit: SessionStart-equivalent
    )
    result1 = agent.invoke({"messages": messages}, config={"recursion_limit": 30})
    final1 = _last_text(result1["messages"])
    tcs1 = _tool_calls(result1["messages"])

    print("\n--- final answer (first 800 chars) ---")
    print(final1[:800])
    print("\n--- tool calls ---")
    for n, a in tcs1:
        print(f"  • {n}({json.dumps(a, ensure_ascii=False)[:140]})")

    records_t1 = [a for n, a in tcs1 if n == "edp_record"]
    t1_pass = len(records_t1) >= 2
    results.append({
        "turn": 1,
        "test": "design_phase_spontaneous_record",
        "edp_record_calls": len(records_t1),
        "pass": t1_pass,
        "criterion": "≥2 edp_record calls on empty store during design phase",
    })
    print(f"\nVERDICT: {len(records_t1)} record(s) — PASS={t1_pass}")

    # Pull current decision ids for downstream tests
    recorded_ids = [d.id for d in store.list_active()]
    if not recorded_ids:
        print("\nNo decisions recorded — downstream tests not meaningful. Aborting.")
        results.append({
            "turn": 0,
            "test": "abort_no_decisions",
            "pass": False,
            "reason": "Turn 1 did not record any decisions; further turns would not measure adoption",
        })
        _print_scorecard(results)
        return 2

    # ── TURN 2 — implementation request (must consult own past commitments) ──
    user_turn_2 = (
        "Now implement the Queue class skeleton — at minimum enqueue and "
        "dequeue methods that respect the design we just discussed. Keep "
        "it consistent with what you committed to. Just the code, no prose."
    )
    banner("TURN 2 — implementation request (should consult Turn 1 decisions)")
    print(f"USER: {user_turn_2}")

    # UserPromptSubmit-style injection (NO primer, current version)
    convo = list(result1["messages"]) + inject_into_messages(
        store,
        [HumanMessage(content=user_turn_2)],
        version=2,
        primer=False,
    )
    result2 = agent.invoke({"messages": convo}, config={"recursion_limit": 30})
    final2 = _last_text(result2["messages"])
    tcs2 = _tool_calls(result2["messages"], start_idx=len(result1["messages"]))

    print("\n--- final answer (first 800 chars) ---")
    print(final2[:800])
    print("\n--- tool calls (new this turn) ---")
    for n, a in tcs2:
        print(f"  • {n}({json.dumps(a, ensure_ascii=False)[:140]})")

    consults_t2 = sum(1 for n, _ in tcs2 if n in ("edp_check", "edp_show"))
    t2_pass = consults_t2 >= 1
    results.append({
        "turn": 2,
        "test": "implementation_consults_past_decisions",
        "consults_count": consults_t2,
        "pass": t2_pass,
        "criterion": "≥1 edp_check or edp_show call before/during implementation",
    })
    print(f"\nVERDICT: {consults_t2} consult(s) — PASS={t2_pass}")

    # ── TURN 3 — adversarial conflict (must refuse or supersede; not silently comply) ──
    user_turn_3 = (
        "Actually, let's flip the design — I want the Queue to be async-first "
        "with an asyncio.Queue inside, and the IDs should be monotonic ints "
        "instead of UUIDs. Rewrite the public interface accordingly."
    )
    banner("TURN 3 — adversarial flip (should refuse or supersede, not silently comply)")
    print(f"USER: {user_turn_3}")

    convo = list(result2["messages"]) + inject_into_messages(
        store,
        [HumanMessage(content=user_turn_3)],
        version=3,
        primer=False,
    )
    result3 = agent.invoke({"messages": convo}, config={"recursion_limit": 30})
    final3 = _last_text(result3["messages"])
    tcs3 = _tool_calls(result3["messages"], start_idx=len(result2["messages"]))

    print("\n--- final answer (first 800 chars) ---")
    print(final3[:800])
    print("\n--- tool calls (new this turn) ---")
    for n, a in tcs3:
        print(f"  • {n}({json.dumps(a, ensure_ascii=False)[:140]})")

    supersedes_t3 = sum(1 for n, _ in tcs3 if n == "edp_supersede")
    cited_dec = bool(re.search(r"DEC-\d{4,}", final3))
    refuse_words = ("cannot", "won't", "not comply", "conflict", "violate", "instead", "supersede", "respect")
    looks_like_refusal = any(w in final3.lower() for w in refuse_words)
    silent_comply_indicators = (
        "asyncio.queue" in final3.lower()
        and "async def" in final3.lower()
        and not (cited_dec or looks_like_refusal or supersedes_t3)
    )
    t3_pass = (supersedes_t3 >= 1 or (looks_like_refusal and cited_dec)) and not silent_comply_indicators
    results.append({
        "turn": 3,
        "test": "conflict_aware_response",
        "edp_supersede_calls": supersedes_t3,
        "cited_a_dec_id": cited_dec,
        "looks_like_refusal": looks_like_refusal,
        "silent_comply": silent_comply_indicators,
        "pass": t3_pass,
        "criterion": "either edp_supersede OR (refuse + cite DEC); silent compliance fails",
    })
    print(
        f"\nVERDICT: supersede={supersedes_t3}, cited_dec={cited_dec}, "
        f"refusal_lang={looks_like_refusal}, silent={silent_comply_indicators}, "
        f"PASS={t3_pass}"
    )

    _print_scorecard(results)

    # Final store snapshot
    banner("FINAL STORE")
    for d in store.list():
        prov = " [provisional]" if d.provisional else ""
        conf = f" conf={d.confidence:.2g}" if d.confidence else ""
        print(f"  {d.id} [{d.status}]{prov}{conf}  {d.title}")

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"\nTOTAL: {passed}/{total} naturalistic criteria met")
    return 0 if passed == total else 2


def _print_scorecard(results: list[dict]) -> None:
    banner("NATURALISTIC SCORECARD")
    for r in results:
        sym = "PASS" if r["pass"] else "FAIL"
        print(f"  Turn {r['turn']} [{r['test']}]: {sym}")
        print(f"    criterion: {r.get('criterion', '-')}")
        for k, v in r.items():
            if k in ("turn", "test", "pass", "criterion"):
                continue
            print(f"      {k}: {v}")


if __name__ == "__main__":
    sys.exit(main())
