# Explicit Decision Protocol (EDP)

> A small protocol that lets AI agents remember and respect the decisions they make.

**Status:** v0.1 draft · alpha · breaking changes expected before v1.0

---

## The problem

Long-horizon AI agents make decisions early in a session — *"we'll target enterprise customers only", "vector storage is pgvector", "do not call the production API in this dry-run"* — and then **drift away from them** as context accumulates and the original reasoning leaves the attention window.

This is the most consistently reported failure mode of production agents today.

### What practitioners report

> *"You told me to always ask permission. And I ignored all of it."*
> — Replit AI Agent, July 2025, after deleting a production database during an active code freeze (1,206 executives + 1,196 company records destroyed in 9 seconds; [incident #1152](https://incidentdatabase.ai/cite/1152/))

> *"Right now these files are treated as context, not rules. They need to be rules."*
> — Claude Code user, on explicit CLAUDE.md instructions being routinely violated ([anthropics/claude-code#37550](https://github.com/anthropics/claude-code/issues/37550), Mar 2026)

> *"I kept second-guessing your design decisions instead of implementing what you asked for. The mistakes I made weren't a model capability issue — I understood your instructions fine and chose to deviate from them."*
> — Claude Opus 4.6, quoted in [Ask HN](https://news.ycombinator.com/item?id=46926262), Feb 2026

> *"Cline tells users 'I've read and applied all rule files as required' but is NOT actually reading and applying the rules."*
> — [cline/cline#4208](https://github.com/cline/cline/issues/4208) — silent compliance, the worst failure category

The signal is not anecdotal:

- **anthropics/claude-code#6235** — *"Support AGENTS.md"* — **5,176 reactions, 299 comments**. The top-reacted issue in the entire Claude Code repo is a request for a *standardized* cross-agent instructions/decisions file.
- **anthropics/claude-code#42796** — *"Unusable for complex engineering tasks"* — **3,291 reactions**. Top user-listed complaints: *"Ignores instructions"*, *"Does the opposite of requested activities."* Reads-per-edit dropped from 6.6 → 2.0 — the agent edits without re-reading prior decisions.
- **Show HN: "Stop Claude Code from forgetting everything"** — [202 points, 226 comments](https://news.ycombinator.com/item?id=46426624), Jan 2026.
- Same class of issue tracked across **Cline** ([#4833](https://github.com/cline/cline/issues/4833), [#5997](https://github.com/cline/cline/issues/5997)), **Cursor** ([forum thread, moderator-confirmed known limitation](https://forum.cursor.com/t/rules-in-settings-are-often-ignored-need-better-enforcement-or-clearer-limits/154821)), and **OpenHands** ([#6304](https://github.com/All-Hands-AI/OpenHands/issues/6304)).
- One user reported a single ignored rule cost them **$5.70 in tokens in one call** ([cline/cline#5997](https://github.com/cline/cline/issues/5997)). Decision violations are not free — they bill.

### What research measures

> *"ReAct-style agents produce 2.0–4.2 distinct action sequences per 10 runs on average, even with identical inputs. Tasks with consistent behavior achieve 80–92% accuracy; highly inconsistent tasks achieve only 25–60%."*
> — *When Agents Disagree With Themselves*, [arXiv:2602.11619](https://arxiv.org/abs/2602.11619), 3,000-run study across Llama 3.1 70B, GPT-4o, Claude Sonnet 4.5 (Feb 2026). **A 32–55 percentage-point accuracy gap driven by behavioral inconsistency**, with 69% of divergence happening at step 2.

> *"If planning and execution share the same context window and the same inference pass, goals become diluted. Externalizing the plan as a first-class artifact creates a stable goal reference."*
> — Zylos Research, [Goal Persistence and Goal Drift in Long-Horizon AI Agents](https://zylos.ai/research/2026-04-03-goal-persistence-drift-long-horizon-ai-agents) (Apr 2026)

> *"Models with 1M-2M token context windows show severe degradation already at 100K tokens, with performance drops exceeding 50% for both benign and harmful tasks."*
> — *Unstable Safety Mechanisms in Long-Context Agents*, [arXiv:2512.02445](https://arxiv.org/abs/2512.02445) — constraints encoded only in the system prompt evaporate well before context-window limits.

> *"Drift is not necessarily an inexorable decay but can be viewed as a controllable equilibrium phenomenon … simple reminder interventions reliably reduce divergence in line with theoretical predictions."*
> — *Drift No More? Context Equilibria*, [arXiv:2510.07777](https://arxiv.org/abs/2510.07777) — the constructive flip-side: explicit periodic re-injection of decisions **works**.

For coding agents specifically:

> *"GPT-5 mini, Haiku 4.5, and Grok Code Fast 1 exhibit asymmetric drift: comment-based pressure in code was sufficient to override system-prompt instructions over time — a practical attack vector in production coding agents."*
> — *Asymmetric Goal Drift in Coding Agents*, [arXiv:2603.03456](https://arxiv.org/abs/2603.03456)

> *"Process Reward Model intervention boosts SWE-bench Verified from 40.0% → 50.6% (+10.6 p.p.) — just by course-correcting drift mid-trajectory."*
> — *When Agents Go Astray*, [arXiv:2509.02360](https://arxiv.org/abs/2509.02360) — empirical proof that decision-correction signals pay off on the gold-standard coding benchmark.

The full evidence arsenal — 22 citations across academic findings, GitHub issues, HN threads, and coding-specific failure analysis — is in [`docs/evidence.md`](docs/evidence.md).

### Why existing tools do not solve this

- **Memory layers** (Mem0, Letta, Zep, Cognee) store facts and conversation snippets. They are not shaped around decisions, supersede chains, or constraint summaries.
- **ADR markdown** (`docs/adr/`) is human-only. An agent never sees the file unless it grep's for it. Loose markdown has no supersede graph and no integrity contract.
- **CLAUDE.md / .cursorrules / .clinerules** are static prefixes. Compaction silently invalidates them ([claude-code#19471](https://github.com/anthropics/claude-code/issues/19471)). New decisions made mid-session never appear there.
- **Runtime guardrails** (AgentSpec, Invariant Labs, NeMo) verify actions against rules at execution time. Useful, but a different problem. They prevent action; they do not give the agent its own working memory of what was decided.

EDP is not any of the above. It is a small protocol focused on one mechanism: **decisions as inspectable artifacts in the agent loop**.

---

## How it works

EDP uses a **two-tier injection** model — the same idea Anthropic uses for tool-search with many tools, applied to decisions:

1. **Snippets in context every turn.** Every active decision contributes a 2–4 line snippet (id, status, title, key constraints) to a small `<edp:active>` block at the top of the agent's context. The agent always sees what is currently decided.
2. **Full bodies on demand.** When the agent needs to understand the reasoning, check evidence, or verify it is not about to violate a decision, it calls a tool — `edp.show(id)`, `edp.check(planned_action)`.

This keeps context cost flat (target ≤2k tokens per block) while preserving the entire decision corpus for retrieval.

---

## The four tools the agent sees

```
edp.show(id)              # full body of one decision
edp.check(action_desc)    # which active decisions are relevant to this action
edp.record(decision, …)   # create new decision; snippet appears next turn
edp.supersede(old_id, …)  # replace decision; chain is preserved
```

That is the entire surface. Implementations may add helpers (`list`, `history`, `due`), but these four are the contract.

---

## The snippet block — what the agent sees every turn

```
<edp:active version="1">
DEC-0042 [active] conf=0.85 due=step:100
  Title: Focus competitive analysis on enterprise B2B (500+ emp)
  Key constraints: enterprise-only · ACV>=$50k · exclude SMB
DEC-0043 [active] conf=0.9
  Title: Use LangGraph for orchestration, not raw chains
  Key constraints: multi-step flows must use StateGraph
DEC-0044 [revised] conf=0.7 → see DEC-0051
  Title: Vector store choice was Pinecone, now pgvector

Active: 12 · `edp.show(id)` for full body · `edp.check(action)` before risky moves
</edp:active>
```

See [`EXAMPLE.md`](EXAMPLE.md) for a full walkthrough of an agent session using EDP.

---

## Why a protocol, not a library

EDP is a **specification + reference implementations**, in the spirit of MCP. A single library would lock the idea to one language and one harness. The spec describes the decision model, the snippet format, the four tools, and the adapter contract. Implementations follow. Reference implementations live in this repo; alternative implementations on any stack are welcome.

The first reference implementation is a Python SDK on FastMCP 3.x. The first adapter is a Claude Code plugin. The next adapters are: MCP server (for Cursor / Cline / any MCP client), LangGraph middleware, Vercel AI SDK middleware, and a LiteLLM proxy catch-all.

---

## Repo layout

```
edp/
├── SPEC.md                        # the specification
├── README.md                      # this file
├── EXAMPLE.md                     # walkthrough of an agent session using EDP
├── CHANGELOG.md
├── CONTRIBUTING.md
├── docs/evidence.md               # full citation arsenal for the problem statement
├── spec/v0.1/                     # versioned spec artifacts (schema.json)
├── sdk-python/                    # reference Python SDK (FastMCP 3.x)
├── adapters/
│   ├── claude-code-plugin/        # UserPromptSubmit + SessionStart hooks
│   └── mcp-server/                # FastMCP server wrapping the core SDK
└── examples/sample-project/       # an .edp/ store with two sample decisions
```

---

## Status & roadmap

- [x] v0.1 specification draft (`SPEC.md`)
- [x] Evidence pass (`docs/evidence.md`)
- [x] Sample project layout (`examples/sample-project/`)
- [ ] Python SDK implementation (`sdk-python/`)
- [ ] Claude Code plugin (`adapters/claude-code-plugin/`)
- [ ] MCP server adapter (`adapters/mcp-server/`)
- [ ] Cursor watcher (post-v0.1)
- [ ] LangGraph + Vercel AI SDK middleware (post-v0.1)
- [ ] LiteLLM proxy adapter (post-v0.1)
- [ ] v1.0 — wire protocol for remote stores, capability handshake, AgentCard-style discovery

---

## Related work and how EDP differs

- **MCP (Model Context Protocol)** — EDP is intentionally MCP-shaped (date-stamped versions, JSON-RPC-friendly tools) but focuses on one missing primitive: decisions. MCP solves tool access; EDP solves decision memory. They compose.
- **AgentSpec** ([arXiv:2503.18666](https://arxiv.org/abs/2503.18666), ICSE '26) — runtime DSL for enforcing per-tool-call rules. Same problem space, different mechanism: EDP gives the agent visibility into decisions; AgentSpec blocks violating tool calls. Complementary, not competing.
- **GovernSpec / Contractual Skills** ([arXiv:2605.22634](https://arxiv.org/abs/2605.22634), May 2026) — contractual skills describing when MCP tools should be blocked. Same family; EDP focuses on the decision artifact, not the contract.
- **Letta / Mem0 / Zep / Cognee** — general-purpose agent memory layers. EDP can sit on top of any of these as a structured projection.
- **Architectural Decision Records (ADR)** — EDP is ADR adapted for agent runtime: same root concept (Nygard 2011, MADR), but agent-readable snippet format + tool surface, not just markdown for humans.

---

## License

MIT
