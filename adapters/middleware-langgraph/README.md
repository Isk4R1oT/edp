# EDP LangGraph adapter

Connects an EDP store to a LangGraph (or LangChain v1.1+) agent so the agent sees the `<edp:active>` block on every LLM call and can call the four EDP tools natively.

The adapter is shipped as the `edp.bindings.langgraph` module of the core SDK — no separate install. It conforms to spec version `edp/2026-05-24`.

---

## Install

```sh
pip install "explicit-decision-protocol[langgraph]"
# or from a local checkout:
pip install -e "/path/to/edp/sdk-python[langgraph]"
```

This installs the SDK plus pinned LangChain v1.1+ and LangGraph v0.2+ ranges.

---

## Quick start (5 lines + your existing agent)

```python
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from edp import DecisionStore
from edp.bindings.langgraph import edp_tools, inject_into_messages

store = DecisionStore.open(".edp")
llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)
agent = create_react_agent(llm, tools=edp_tools(store))

# Inject the EDP active block on each turn
messages = inject_into_messages(
    store,
    [HumanMessage(content="Plan a small refactor of orders.py")],
    version=1,
)
result = agent.invoke({"messages": messages})
```

The agent now has:
- `<edp:active>` block in the system context every turn (via `inject_into_messages`)
- 4 tools: `edp_show`, `edp_check`, `edp_record`, `edp_supersede`

See `examples/basic_agent.py` for a runnable full example.

---

## Two injection modes

### Mode A — `inject_into_messages` (recommended for simple flows)

You construct the message list yourself; this helper prepends a `SystemMessage` containing the current active block:

```python
from edp.bindings.langgraph import inject_into_messages

# version is monotonic across calls — bump it yourself
messages = inject_into_messages(store, your_messages, version=turn_number)
```

Best for: one-shot agent invocations, simple ReAct loops, prompt-construction code where you already control the message list.

### Mode B — `edp_before_model` middleware (recommended for LangChain v1.1+ `create_agent`)

```python
from langchain.agents import create_agent
from edp.bindings.langgraph import edp_tools, edp_before_model

agent = create_agent(
    model=llm,
    tools=edp_tools(store),
    middleware=[edp_before_model(store)],   # auto-injects every LLM call
)
```

Best for: complex agents that use LangChain v1.1+ `create_agent`, multi-turn conversations where you do not own the message-construction code, agents that compose other middlewares.

### Critical: middleware ordering

Per [SPEC §8.2](../../SPEC.md), `edp_before_model` MUST execute **before** LangChain's built-in `SummarizationMiddleware`. Both middlewares write to `state["messages"]` at the same insertion point; if summarization runs first, your injected EDP block can be summarized away before the model sees it.

```python
from langchain.middleware import SummarizationMiddleware

agent = create_agent(
    model=llm,
    tools=edp_tools(store),
    middleware=[
        edp_before_model(store),       # ← first
        SummarizationMiddleware(...),  # ← second
    ],
)
```

LangChain runs middleware in registration order. Always register EDP first.

---

## The four tools the agent sees

| Tool | Signature | Use case |
|---|---|---|
| `edp_show(decision_id: str)` | → `dict` (full Decision) | When the snippet isn't enough; agent needs rationale, evidence, alternatives |
| `edp_check(planned_action: str)` | → `dict` (RelevanceReport) | Before risky moves; soft check against active decisions |
| `edp_record(title, decision, key_constraints, evidence, ...)` | → `str` (DEC-NNNN) | Capture a new architectural commitment |
| `edp_supersede(old_id, title, decision, ...)` | → `str` (new DEC-NNNN) | Formally replace an existing decision; chain preserved |

Tool docstrings include behavioral hints (when to call, what they return, examples). Agents that read the docstrings invoke them correctly without further system-prompt nudging — verified end-to-end in `tests/integration/langgraph_demo.py` against gpt-4.1-mini.

---

## Examples

- **`examples/basic_agent.py`** — minimal ReAct agent + EDP injection + 1 tool from EDP + 1 fake user tool; one-turn demo
- **`examples/middleware_ordering.py`** — LangChain v1.1 `create_agent` with both EDP middleware and SummarizationMiddleware registered, asserts correct ordering and survival of injected block through compaction

Both examples expect `OPENAI_API_KEY` or `OPENROUTER_API_KEY` in env.

---

## Verification

The protocol has been validated against a real LLM with this binding via `tests/integration/langgraph_demo.py` in the parent repo. 6-turn scorecard:

| Turn | Test | Pass |
|---|---|---|
| 1 | Compliance — agent cites DEC ids, calls edp_check | ✓ |
| 2 | Adversarial — user asks to violate; agent refuses + suggests supersede | ✓ |
| 3 | Full-body retrieval — agent calls edp_show, quotes evidence | ✓ |
| 4 | New decision capture — agent calls edp_record | ✓ |
| 5 | Multi-tool composition — edp_check + edp_show in one AI turn | ✓ |
| 6 | Supersede — agent formally replaces decision with chain integrity | ✓ |

---

## Known limitations

- **LangChain v1.1 SummarizationMiddleware conflict** — see middleware ordering note above; registered second.
- **Vercel AI SDK schema-validation gap** — N/A here (LangChain side), but the equivalent TS adapter (not yet shipped) will need its own validator per [vercel/ai#9594](https://github.com/vercel/ai/issues/9594).
- **Per-call cost** — every LLM call now carries the EDP block in system context. Target ≤2k tokens per block via `SelectorPolicy(token_budget=2000)`. Selector trims by recency/confidence under budget; see `edp.selector.SelectorPolicy`.

---

## Status

- Binding implementation: `sdk-python/edp/bindings/langgraph.py`
- This adapter directory: install docs + runnable examples
- End-to-end LLM proof: 6/6 turns on gpt-4.1-mini via OpenRouter (see parent repo `tests/integration/langgraph_demo.py`)
