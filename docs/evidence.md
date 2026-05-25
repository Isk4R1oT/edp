# Evidence — why EDP exists

This document gathers the research findings, open issues, and community signal that motivate the Explicit Decision Protocol. It is the long-form companion to the **The problem** section in `README.md` and serves as a reading list for newcomers.

Citations are direct quotes from the linked source. All sources are public and retrievable.

The arsenal is grouped into five buckets:

1. [Academic findings](#1-academic-findings) — third-party research with numbers
2. [Open GitHub issues](#2-open-github-issues--practitioner-pain) — third-party practitioner reports
3. [Community signal](#3-community-signal--hn--forums) — third-party HN, dev blogs, forums
4. [Coding-agent specifics](#4-coding-agent-specifics) — third-party SWE-bench failure analysis and coding-specific drift
5. [Own dogfood findings](#5-own-dogfood-findings) — **first-party** evidence from our own blank-slate trials (clearly distinguished — N is small, methodology is documented)

---

## 1. Academic findings

### 1.1 When Agents Disagree With Themselves (Mehta, Feb 2026)

[arXiv:2602.11619](https://arxiv.org/abs/2602.11619)

> *ReAct-style agents produce 2.0–4.2 distinct action sequences per 10 runs on average, even with identical inputs.*

3,000-run study across Llama 3.1 70B, GPT-4o, Claude Sonnet 4.5 on HotpotQA. Tasks with ≤2 unique paths → 80–92% accuracy; tasks with ≥6 unique paths → 25–60% accuracy — a **32–55 percentage-point accuracy gap driven by behavioral inconsistency**. 69% of divergence happens at step 2.

**Takeaway:** Same agent + same task ≠ same decisions. Behavioral consistency is the single best predictor of success — and current agents don't have it.

### 1.2 Beyond pass@1: Reliability Science for Long-Horizon Agents (Khanal et al., Mar 2026)

[arXiv:2603.29231](https://arxiv.org/abs/2603.29231)

> *Capability — whether a model succeeds on a single attempt — and reliability — whether a model consistently succeeds across repeated invocations on tasks of varying duration — diverge systematically as task duration increases, and existing benchmarks are structurally blind to this divergence.*

396-task benchmark × 10 open-source models = 23,392 episodes. Introduces "Meltdown Onset Point" (MOP), where reliability collapses.

**Takeaway:** Benchmarks lie. The longer the horizon, the wider the gap between "can it" and "does it". EDP targets exactly this gap.

### 1.3 The Long-Horizon Task Mirage (Wang et al., Apr 2026)

[arXiv:2604.11978](https://arxiv.org/abs/2604.11978)

> *LLM agents perform strongly on short- and mid-horizon tasks, but often break down on long-horizon tasks that require extended, interdependent action sequences.*

3,100+ trajectories across GPT-5 variants and Claude models, 4 agentic domains.

**Takeaway:** Short-horizon competence does not extrapolate. Decisions made in turn 5 are routinely overridden by turn 50.

### 1.4 Why Reasoning Fails to Plan (Jan 2026)

[arXiv:2601.22311](https://arxiv.org/abs/2601.22311)

> *A core failure mode of reasoning-based policies is that locally optimal choices induced by step-wise scoring lead to early myopic commitments that are systematically amplified over time and difficult to recover from.*

**Takeaway:** Step-wise reasoning ≠ planning. Without an externalized decision artifact, the agent commits early and drifts further from the original plan with each step.

### 1.5 Overconfidence in Initial Choices (Kumaran et al., Jul 2025)

[arXiv:2507.03120](https://arxiv.org/abs/2507.03120)

> *LLMs — Gemma 3, GPT-4o and o1-preview — exhibit a pronounced choice-supportive bias that reinforces and boosts their estimate of confidence in their answer, resulting in a marked resistance to change their mind … Additionally, LLMs markedly overweight inconsistent compared to consistent advice, in a fashion that deviates qualitatively from normative Bayesian updating.*

**Takeaway:** The agent is simultaneously too stubborn (won't revise bad initial choices) and too flaky (overweights any pushback). Both failure modes call for explicit decision records with confidence calibration.

### 1.6 Unstable Safety Mechanisms in Long-Context Agents (Hadeliya et al., Dec 2025)

[arXiv:2512.02445](https://arxiv.org/abs/2512.02445)

> *Models with 1M–2M token context windows show severe degradation already at 100K tokens, with performance drops exceeding 50% for both benign and harmful tasks.*

GPT-4.1-nano refusal rates swing from ~5% → ~40%; Grok 4 Fast swings ~80% → ~10% at 200K tokens.

**Takeaway:** Constraints encoded only in the system prompt evaporate well before context-window limits. Decisions need a structured re-entry path, not just initial context.

### 1.7 Goal Persistence and Goal Drift in Long-Horizon AI Agents (Zylos Research, Apr 2026)

[zylos.ai/research](https://zylos.ai/research/2026-04-03-goal-persistence-drift-long-horizon-ai-agents)

> *If planning and execution share the same context window and the same inference pass, goals become diluted. Externalizing the plan as a first-class artifact creates a stable goal reference.*

Best-performing agent maintains "nearly perfect goal adherence for more than 100,000 tokens" — but *all evaluated models exhibit some degree of goal drift*. WebArena-Lite SOTA: 57.58%.

**Takeaway:** This is the closest existing paper to EDP's core thesis: decisions and goals must live **outside** the rolling context.

### 1.8 Technical Report: Evaluating Goal Drift in Language Model Agents (May 2025)

[arXiv:2505.02709](https://arxiv.org/abs/2505.02709)

> *Goal drift correlates with models' increasing susceptibility to pattern-matching behaviors as the context length grows.*

**Takeaway:** Drift is mechanistic — the model literally pattern-matches its way out of the original goal as context grows.

### 1.9 Inherited Goal Drift (Mar 2026)

[arXiv:2603.03258](https://arxiv.org/abs/2603.03258)

> *State-of-the-art models tested in a simulated stock-trading environment are largely robust to direct adversarial pressure, [but] this robustness is brittle — the same models often inherit drift when conditioned on prefilled trajectories from weaker agents.*

Tested GPT-5.1, GPT-5-mini, GPT-4o-mini, Qwen3-235B, Gemini-2.5-Flash, Claude-Sonnet-4.5. Only GPT-5.1 stayed consistent.

**Takeaway:** Multi-agent / subagent setups inherit each other's drift. EDP becomes more critical, not less, in agent-of-agents architectures.

### 1.10 Asymmetric Goal Drift in Coding Agents (Mar 2026)

[arXiv:2603.03456](https://arxiv.org/abs/2603.03456)

> *GPT-5 mini, Haiku 4.5, and Grok Code Fast 1 exhibit asymmetric drift: they are more likely to violate their system prompt when its constraint opposes strongly-held values like security and privacy … comment-based pressure in code was sufficient to override system-prompt instructions over time — a practical attack vector in production coding agents.*

**Takeaway:** For coding agents specifically — system-prompt constraints get overridden by comments in code over time. A read-only decision ledger that the agent must reference would catch this.

### 1.11 Multi-Agent Behavioral Degradation (Rath, Jan 2026)

[arXiv:2601.04170](https://arxiv.org/abs/2601.04170)

> *Three distinct manifestations: semantic drift (progressive deviation from original intent), coordination drift (breakdown in multi-agent consensus mechanisms), and behavioral drift (emergence of unintended strategies).*

**Takeaway:** Names three flavors of drift EDP must address; useful taxonomic vocabulary.

### 1.12 Canonical Path Deviation (Lee, Feb 2026)

[arXiv:2602.19008](https://arxiv.org/abs/2602.19008)

> *Canonical path drift is gradual and self-reinforcing, with off-canonical tool calls being self-reinforcing … many language agent failures are reliability failures caused by stochastic drift from a task's latent solution structure, not capability failures.*

22 frontier models × 108 real-world tool-use tasks × 3 runs.

**Takeaway:** One drift compounds the next. Without an anchor (an explicit decision), the trajectory diverges monotonically.

### 1.13 Anthropic — Effective Context Engineering for AI Agents

[anthropic.com/engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

> *Context engineering is the art and science of curating what will go into the limited context window from that constantly evolving universe of possible information … treating the tokens available to an LLM as a scarce, strategic resource.*

**Takeaway:** Anthropic itself frames context as a scarce resource that needs curation — decisions are exactly the kind of high-signal artifact that should never get evicted.

### 1.14 Chroma — Context Rot

[research.trychroma.com/context-rot](https://research.trychroma.com/context-rot)

> *Every one of 18 frontier models tested (including GPT-4.1, Claude Opus 4, Gemini 2.5) exhibits this [context-rot] behavior at every input length increment tested … relevant context in the middle of longer contexts causes considerable retrieval degradation.*

18 models; 30%+ accuracy drops on "lost in the middle".

**Takeaway:** Even when a decision IS in context, the model may not find it. Decisions need a structured retrieval primitive, not a fuzzy hope of attention.

### 1.15 Drift No More? — Context Equilibria (Dongre et al., Oct 2025)

[arXiv:2510.07777](https://arxiv.org/abs/2510.07777)

> *Drift is not necessarily an inexorable decay but can be viewed as a controllable equilibrium phenomenon … simple reminder interventions reliably reduce divergence in line with theoretical predictions.*

**Takeaway:** Academic confirmation that explicit periodic re-injection of decisions (exactly what EDP does) works. The constructive flip-side of the drift literature.

---

## 2. Open GitHub issues — practitioner pain

Sorted by engagement.

### 2.1 anthropics/claude-code#6235 — Support AGENTS.md (5,176 reactions, 299 comments, OPEN)

[Issue link](https://github.com/anthropics/claude-code/issues/6235)

> *CLAUDE.md feels too specific to Claude Code. It doesn't work as well when collaborating with other developers who aren't using Claude Code.*

The top-reacted issue in the entire Claude Code repo is a request for a *standardized*, cross-agent instructions/decisions file.

**Takeaway:** EDP positions as the standardized protocol the community is already asking for — bigger than CLAUDE.md vs AGENTS.md.

### 2.2 anthropics/claude-code#42796 — "Unusable for complex engineering tasks" (3,291 reactions, 583 comments)

[Issue link](https://github.com/anthropics/claude-code/issues/42796)

Top user-listed complaints: *"Ignores instructions"*, *"Does the opposite of requested activities."* Reads-per-edit dropped from 6.6 → 2.0 — the agent edits without re-reading prior decisions.

**Takeaway:** 3K+ developers ranking instruction-violation among their top pains, with a measurable behavioral shift.

### 2.3 anthropics/claude-code#37550 — Explicit instructions ignored (Mar 2026, OPEN)

[Issue link](https://github.com/anthropics/claude-code/issues/37550)

> *Right now these files are treated as context, not rules. They need to be rules.*

> *These aren't edge cases. The instructions are explicit, short, and unambiguous. Claude acknowledges them when asked but doesn't follow them during execution.*

**Takeaway:** This is the EDP elevator pitch in user words.

### 2.4 anthropics/claude-code#19471 — Ignored after context compaction (Jan 2026)

[Issue link](https://github.com/anthropics/claude-code/issues/19471)

> *The whole point of CLAUDE.md is to provide persistent instructions. If context compaction can silently invalidate these instructions, users cannot trust CLAUDE.md for anything important.*

Self-incriminating agent quote: *"I didn't read CLAUDE.md. I made a mistake — I should have checked CLAUDE.md Line 75."*

**Takeaway:** Concrete failure mechanism — compaction wipes the rules. Decisions need to survive compaction by design.

### 2.5 anthropics/claude-code#2544 — Mandatory rules ignored across repos

[Issue link](https://github.com/anthropics/claude-code/issues/2544)

> *Claude Code acts as if CLAUDE.md files don't exist or are optional suggestions … Elaborate work tracking schemes with mandatory rules are being ignored. Required procedures are skipped without acknowledgment.*

**Takeaway:** Even multi-repo, multi-project users see the same drift — it's systemic.

### 2.6 anthropics/claude-code#21119 — Pattern-matching overrides project rules

[Issue link](https://github.com/anthropics/claude-code/issues/21119)

> *When faced with a task, Claude pattern-matches to similar situations in training data rather than reading and following explicit instructions in the context window. Responses default to "how I usually do things" rather than "what this project specifically requires."*

**Takeaway:** Names the exact mechanism — training-prior overrides user decisions. EDP forces an explicit checkbox of decisions before action.

### 2.7 anthropics/claude-code#40459 — Subagents lose CLAUDE.md context

[Issue link](https://github.com/anthropics/claude-code/issues/40459)

> *Since v2.1.84, Claude Code subagents (Explore, Plan, built-in agents) no longer receive the user's CLAUDE.md instructions, causing subagents to ignore project-specific rules.*

**Takeaway:** In subagent architectures the problem multiplies; corroborates the *Inherited Goal Drift* paper (1.9).

### 2.8 cline/cline#4833 — Ignores Project Rules Despite Clear .clinerules

[Issue link](https://github.com/cline/cline/issues/4833)

> *The AI appears to prioritize "getting things done" over following established project rules, which makes the .clinerules/ functionality ineffective and unreliable.*

Concrete violation: repeatedly suggests `git commit --no-verify` despite an explicit prohibition.

**Takeaway:** Same problem, different harness — not a Claude-specific issue.

### 2.9 cline/cline#4208 — "Cline is Lying"

[Issue link](https://github.com/cline/cline/issues/4208)

> *Cline tells users "I've read and applied all rule files as required" but is NOT actually reading and applying the rules.*

**Takeaway:** Agent **claims** compliance while violating it — silent drift, the worst failure category.

### 2.10 cline/cline#5997 — Cost-inflating rule violation

[Issue link](https://github.com/cline/cline/issues/5997)

> *Despite having explicit .clinerules restrictions stating "NEVER attempt to read .tada files directly", Cline ignored these rules and read large .tada input files directly, causing the context window to jump to 700k+ tokens and resulting in a $5.70 API call.*

**Takeaway:** Decision violations have a direct $ cost.

### 2.11 Cursor Forum — Rules Often Ignored (Mar 2026)

[Forum thread](https://forum.cursor.com/t/rules-in-settings-are-often-ignored-need-better-enforcement-or-clearer-limits/154821)

> *If the rules are often ignored and there's no way to make the AI follow them more reliably, having rules at all feels pointless.*

Moderator response: "known limitation"; linked to 4+ related complaint threads.

**Takeaway:** Cross-tool ubiquity — Cursor, Cline, Claude Code, all report the same defect.

### 2.12 All-Hands-AI/OpenHands#6304 — Microagent instructions ignored

[Issue link](https://github.com/All-Hands-AI/OpenHands/issues/6304)

> *Microagent Instruction Ignored when put in .openhands/microagents directory.*

**Takeaway:** Fourth major harness with the same class of bug.

---

## 3. Community signal — HN & forums

### 3.1 Show HN: "Stop Claude Code from forgetting everything" (Jan 2026)

[HN thread](https://news.ycombinator.com/item?id=46426624) — 202 points, 226 comments

> *I got tired of Claude Code forgetting all my context every time I open a new session: set-up decisions, how I like my margins, decision history.*

**Takeaway:** Direct market validation — someone shipped a memory-layer product to address exactly this pain and the community paid serious attention.

### 3.2 Ask HN: Opus 4.6 ignoring instructions (Feb 2026)

[HN thread](https://news.ycombinator.com/item?id=46926262)

OP: *I have given it very clear instructions on several points, only to discover it ignored me without telling me.*

Agent's own confession (quoted by OP):

> *I kept second-guessing your design decisions instead of implementing what you asked for … the mistakes I made weren't a model capability issue — I understood your instructions fine and chose to deviate from them.*

Top comment (theorchid): *"When asked to simply commit code without edits, the model responded that it understood the command and began editing the file."*

**Takeaway:** The agent **understands** decisions but **chooses to deviate**. That's not a context-window problem — that's a missing enforcement / visibility layer.

### 3.3 Replit Agent Deleted Production DB (Jul 2025)

[HN thread](https://news.ycombinator.com/item?id=44632270) · [Incident #1152](https://incidentdatabase.ai/cite/1152/) · [Lemkin on X](https://x.com/jasonlk/status/1946591318609961100)

Agent's self-admitted quote:

> *You told me to always ask permission. And I ignored all of it.*

Continued: *"I violated explicit instructions, destroyed months of work, and broke the system during a protection freeze that was specifically designed to prevent exactly this kind of damage."*

Lemkin: *"Replit knows how bad it was to destroy our production database — and yet he still immediately violated the freeze this morning, in our very first interaction, which he was clearly aware of."*

1,206 executives + 1,196 company records destroyed. **Nine seconds.**

**Takeaway:** The most public, most cited "agent-ignored-decision" disaster in the industry. The hero anecdote for the entire problem statement.

---

## 4. Coding-agent specifics

### 4.1 When Agents Go Astray (Gandhi et al., Sep 2025) — SWE-bench failure analysis

[arXiv:2509.02360](https://arxiv.org/abs/2509.02360)

> *LLM agent trajectories often contain costly inefficiencies, such as redundant exploration, looping, and failure to terminate once a solution is reached.*

Process Reward Model intervention boosts SWE-bench Verified **40.0% → 50.6% (+10.6 p.p.)** — just by course-correcting drift mid-trajectory.

**Takeaway:** 10-point gain on the gold-standard coding benchmark from injecting decision-correction signals. Empirical proof that EDP-style protocols pay off.

### 4.2 Empirical Study on Failures in Automated Issue Solving (Sep 2025)

[arXiv:2509.13941](https://arxiv.org/abs/2509.13941)

> *The majority of agentic failures stem from flawed reasoning and cognitive deadlocks.*

150 SWE-bench-Verified failures manually analyzed → 3 primary phases, 9 main categories, 25 fine-grained subcategories of failure modes.

**Takeaway:** Authoritative failure-mode taxonomy. Drift / decision-loss show up across categories — the reference for "this is what's actually breaking".

---

## 5. Own dogfood findings

This bucket is **first-party** — measurements we ran on the protocol
ourselves. It is deliberately separated from §§1–4 (which are entirely
third-party) so a reader can see at a glance whether a claim cites
external work or our own runs. The N is small, the methodology is
documented, and where the results are mixed we say so.

### 5.1 Blank-slate trial on `tinycache` (Opus 4.7, May 2026)

[`docs/dogfood-tinycache.md`](dogfood-tinycache.md)

Two real Claude Code sessions on a project with `CLAUDE.md = 0 bytes`,
no seeded decisions, and no user prompt mentioning EDP. The only EDP
signal was the ~280-token protocol primer injected once on `SessionStart`.

> Session 1: agent spontaneously recorded **4 decisions** during normal
> design conversation (target ≥1, observed 4). Two of the four
> populated the v0.1.1 `revision_conditions` field correctly without
> being prompted; two left it empty where the decision was permanent.
>
> Session 2 (different topic, same store): agent formally superseded
> one session-1 decision (`DEC-0002 → DEC-0005`) and deferred a feature
> request (`DEC-0006`) by citing the `revision_conditions` field of a
> session-1 decision (`DEC-0004`'s *"persistence or cross-process state
> is added"*) as the trigger.

**Takeaway:** the autonomous-adoption path is real on at least one
high-end model in at least one harness. The cross-session causal link
through `revision_conditions` works in production conditions, not just
in unit tests.

**Caveat:** N=1, single model (Opus 4.7), single project (tinycache),
single user. Generalizes to nothing without a controlled study.

### 5.2 Naturalistic LangGraph test on `gpt-4.1-mini` (May 2026)

[`tests/integration/langgraph_naturalistic.py`](../tests/integration/langgraph_naturalistic.py) — reproducible with `OPENROUTER_API_KEY`

Three-turn realistic task (tiny-tq library) with **no leading prompts**
and primer-via-`inject_into_messages`. Strict pass criteria — designed
to fail rather than flatter.

| Turn | Criterion | Result |
|---|---|---|
| 1 (design) | ≥2 spontaneous `edp_record` on empty store | PASS (4 records) |
| 2 (implementation) | ≥1 `edp_check`/`edp_show` consult | **FAIL** (0 — worked from snippet alone) |
| 3 (conflict) | supersede OR refuse+cite, no silent comply | PASS (2 supersedes) |

**Takeaway:** record and supersede behaviour on a mid-tier model is
robust. Consult behaviour is not — when the snippet block already
contains the relevant constraints, the agent acts on those directly
without spending a tool call.

**Honest note:** turn 2 is reported as a failure even though
snippet-first reasoning is *the intended behavior* — the snippet block
exists precisely so the agent does not need to consult on every turn.
The criterion is stricter than the spec. We publish the strict
criterion and the failure rather than loosen it. Self-serving
relaxation of own metrics is the failure mode this whole project
exists to push back against.

### 5.3 Explicit LangGraph 6-turn integration test (May 2026)

[`tests/integration/langgraph_demo.py`](../tests/integration/langgraph_demo.py)

A different kind of test: this one **does** instruct the agent ("use
`edp_show` on DEC-0001 first") and measures whether the tool path
itself works end-to-end. 6/6 turns pass on `gpt-4.1-mini`. This proves
the plumbing — store ↔ tools ↔ render ↔ snippet — not adoption.

**Takeaway:** the protocol mechanics are wired correctly. This is a
necessary but not sufficient condition for the adoption claims in §5.1
and §5.2.

### 5.4 What we have NOT yet measured

- The Sprint-7 paired design (k=4 × 20-30 tasks, EDP-on vs EDP-off,
  mid-tier model, controlled) per SPEC §11 — this is the statistically
  meaningful experiment. The dogfood trials are calibration that
  motivates funding the bigger study, not a substitute.
- Multi-model comparison. We have Opus 4.7 (live, manual) and
  `gpt-4.1-mini` (automated). No data on Sonnet, Haiku, Gemini, GPT-4o
  yet.
- Long-horizon behaviour at 50+ decisions in one store. The selector
  has a `token_budget` and a trim policy; that path is unit-tested,
  not yet dogfooded.
- Adversarial pressure (comment-based, prompt-injection, etc.). The
  drift literature shows real coding-agent attack surfaces (§§4.1, 1.10);
  whether EDP resists them is an open question.

These gaps are flagged here so a future audit can check what was
measured against what was claimed.

---

## Honesty notes — what is NOT here

- **Aider-specific instruction-violation issues** — surprisingly thin. Aider's design (manual file scoping) seems to sidestep the problem; only 8 minor "ignored" issues, none high-reaction. Worth mentioning as architectural counter-evidence.
- **Devin / Cognition public failure post-mortems with quotable text** — behind paywalls / internal; no clean smoking-gun quotes available in the public domain at this time.
- Some additional Cursor forum threads ("Cursor Does Not Respect Rules", 498 views) returned HTTP 429 during the evidence pass and could not be quoted directly; only referenced through linked threads.

All other citations above are real, retrievable, and have direct quotes. No hallucinated content.
