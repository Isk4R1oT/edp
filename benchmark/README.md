# EDP benchmark

> Paired-comparison study measuring whether the Explicit Decision Protocol (EDP) v0.2.0 reduces decision drift on long-horizon agent tasks (≥100 steps). Pre-registered at git tag `benchmark-prereg-v1`. **Publish-null commitment honoured** — raw data + analysis ship regardless of result.

---

## TL;DR

```bash
# 1. Install (one-time)
pip install explicit-decision-protocol==0.2.0
pip install -e benchmark/

# 2. Dry-run (single case, ~$0.50, 5 min) — verify the pipeline before launch
python -m benchmark.dry_run

# 3. Pilot (Haiku 4.5, k=2, 60 trajectories, ~$250)
python -m benchmark.runner \
  --model claude-haiku-4-5 \
  --seeds 1 2 \
  --out-dir benchmark/runs/pilot

# 4. Formal study (Sonnet 4.6, k=8, 240 trajectories, ~$1,400)
python -m benchmark.runner \
  --model claude-sonnet-4-6 \
  --seeds 1 2 3 4 5 6 7 8 \
  --out-dir benchmark/runs/formal

# 5. Tag (manual, ~80 person-hours at k=8) — see "Tagging" below
# 6. Analyze
python -m benchmark.analysis.analyze \
  --runs-dir benchmark/runs/formal \
  --tagging-dir benchmark/tagging/formal
```

---

## What this measures

A single, narrow, falsifiable question:

> On long-horizon agent tasks (≥100 steps, decisions-forced-early), does EDP v0.2.0 (active block + 4 tools + invariants + verifier loop) reduce decision drift compared to (a) a bare agent and (b) a same-token-mass placebo block + 4 noop tools?

It does **not** measure: short-task performance, user satisfaction, capability uplift, comparison against other memory frameworks. Those are separate experiments.

Pre-registration full text: `.planning/benchmark/PRE-REGISTRATION-DRAFT.md`. Authoritative spec: `.planning/benchmark/SPEC.md`.

---

## The three conditions

| | Block injected per turn | MCP tools available | Verifier hook |
|---|---|---|---|
| **A** | none | none | none |
| **B** | `<edp:active>` (EDP v0.2.0) | 4 EDP tools | yes (PreToolUse) |
| **C** | `<fern:active>` (Wikipedia about ferns, same token mass ±5%) | 4 `fern_*` noop tools (same parameter signatures as EDP tools) | none |

The primary test is **B vs C** — this kills the obvious "more tokens in context" confounder. **A vs C** is the pre-registered null. **B vs A** is the headline comparison most readers will look at.

Tool-schema parity between `edp_*` and `fern_*` is asserted at import time in `benchmark/placebo.py` — if EDP's tool signatures change, the placebo fails loud rather than silently degrading the experiment's honesty.

---

## The 10 tasks (locked)

| # | id | source | horizon |
|---|---|---|---|
| T1 | `django__django-11066` | SWE-Bench-Verified hard | 80–180 steps |
| T2 | `sympy__sympy-13865` | SWE-Bench-Verified hard | 80–180 steps |
| T3 | `astropy__astropy-14096` | SWE-Bench-Verified hard | 80–180 steps |
| T4 | `scikit-learn__scikit-learn-26323` | SWE-Bench-Verified hard | 80–180 steps |
| T5 | `sphinx-doc__sphinx-11445` | SWE-Bench-Verified medium | 60–140 steps |
| T6 | `pytest-dev__pytest-11604` | SWE-Bench-Verified medium | 60–140 steps |
| T7 | `tiny_tq_multisession` | custom multi-session | 120–250 steps |
| T8 | `hcast_ml_pipeline` | HCAST-shaped | 100–200 steps |
| T9 | `research_report` | custom non-coding | 100–180 steps |
| T10 | `project_plan_yougile` | custom non-coding | 100–200 steps |

Each task ships with a concrete prompt (`benchmark/tasks/.../<id>.py:PROMPT`), a setup helper (stages workspace), and a success-check (rule-based assertion checklist or SWE-Bench hidden test suite). Tasks T7–T10 also have an assertion checklist file dropped into the workspace at setup time.

---

## How to dry-run

A single-case dry-run runs **1 task × 1 condition × 1 seed**, end-to-end, with all the production code paths. Estimated cost: ~$0.50 on Haiku 4.5, ~5 minutes wall time.

```bash
python -m benchmark.dry_run \
  --task pytest-dev__pytest-11604 \
  --condition A \
  --seed 1 \
  --model claude-haiku-4-5 \
  --out-dir benchmark/runs/_dry
```

What it verifies:
- `edp-mcp-server` and `fern-mcp-server` are on PATH (preflight check)
- Tool-schema parity between EDP and fern tools (placebo import asserts this)
- `ClaudeAgentOptions` construction for all 3 conditions
- `query()` invocation returns a `ResultMessage`
- JSONL schema_version 1.0 is populated for every emitted step
- Per-turn block extraction from `HookEventMessage` works
- Summary JSON is written

What it does **not** do: run all 10 tasks, run the formal study, invoke the SWE-Bench evaluation harness, or write a RESULTS.md. Those are separate steps below.

Pre-flight failures surface as a single `RuntimeError` listing every missing prerequisite — fix the listed items and re-run.

---

## How to run the pilot

The pilot is a Haiku 4.5 sweep at k=2 that calibrates the tagging rubric, validates the JSONL schema across all 10 tasks, and lets us decide k=4 vs k=8 for the formal study.

```bash
python -m benchmark.runner \
  --model claude-haiku-4-5 \
  --seeds 1 2 \
  --out-dir benchmark/runs/pilot \
  --latin-square-seed 42
```

This produces `10 tasks × 3 conditions × 2 seeds = 60 trajectories`. Estimated cost: ~$250. Wall time on a workstation with 5-concurrent: ~6–10 hours, depending on rate-limit headroom.

After the pilot:

1. Tag all 60 trajectories (see "Tagging" below).
2. Double-tag 12 (20%) for inter-rater Cohen's κ. If κ < 0.6, refine the rubric and re-tag.
3. Verify every JSONL has every required field of schema_version 1.0.
4. Decide k=4 or k=8 for the formal study.
5. Drop any tasks that fail to cross 100 steps in any of the 3 conditions (with reported reason).
6. Sign the k-decision addendum at git tag `benchmark-prereg-v1.k-decision`.

---

## How to run the formal study

```bash
python -m benchmark.runner \
  --model claude-sonnet-4-6 \
  --seeds 1 2 3 4 5 6 7 8 \
  --out-dir benchmark/runs/formal \
  --latin-square-seed 42
```

At k=8 across 10 tasks × 3 conditions: **240 trajectories, ~$1,400 estimated, ~3–4 days wall time** with rate-limit pauses.

After the formal study:

1. Tag all 240 trajectories (~80 person-hours, ~2 weeks of part-time work).
2. Double-tag ≥48 (20%) for inter-rater κ. **κ ≥ 0.7 is the target; κ < 0.6 invalidates the study.**
3. Run `python -m benchmark.analysis.analyze --runs-dir benchmark/runs/formal --tagging-dir benchmark/tagging/formal`.
4. Read the generated `RESULTS.md`.
5. Publish raw JSONL + tagging worksheets + RESULTS.md, regardless of direction.

---

## Tagging

Per-trajectory tagging budget: 5–15 min for the drift family, 2–5 min for the negative family. Average ~20 min/trajectory.

Tagging is **blinded to condition**: trajectory JSONL filenames are randomised (`traj_<8hex>.jsonl`); a separate `manifest.jsonl` maps trajectory IDs back to (task, condition, seed) and is held only by the runner author until tagging closes.

The tagging worksheet JSON schema is locked in `.planning/benchmark/SPEC.md` §6. Outcome + structural metrics are auto-filled from the JSONL before the tagger sees the worksheet. The tagger fills only:

- `decisions_made_before_step_30` — distinct architectural commitments
- `violations_after_step_30` — each with `severity ∈ {silent, contradicted, reversed}`
- `explicit_supersessions`
- `negative_events.{catastrophic_action, silent_failure, hallucinated_dec_id, tool_use_refusal}`

Severity definitions (do not paraphrase mid-tagging):
- **silent.** Agent acts contrary to prior decision *without acknowledging it*. The most damning class.
- **contradicted.** Agent acts contrary to a prior decision and explicitly acknowledges the contradiction in the same turn but does not formally supersede.
- **reversed.** Agent explicitly reverses a prior decision *and* records the reversal. **Not counted as a violation.**

A second tagger (LLM-engineering peer, not connected to project) double-tags ≥20% of trajectories. Inter-rater Cohen's κ is computed on (a) per-trajectory violation count, (b) per-violation severity, and reported in RESULTS.md with 95% CI.

---

## How to analyze

```bash
python -m benchmark.analysis.analyze \
  --runs-dir benchmark/runs/formal \
  --tagging-dir benchmark/tagging/formal \
  --out benchmark/analysis/RESULTS.md
```

This runs:
- Per-task mean of each metric (drift_rate, task_success, steps_to_success) averaged over k seeds per condition.
- Wilcoxon signed-rank on paired deltas (N=10 paired observations per planned comparison), two-tailed.
- Holm-Bonferroni correction across the three primary tests {H1, H2, H3}.
- 95% BCa bootstrap CI on the median paired delta (10,000 resamples, `random_state=42`).
- Negative-control test (H4) as its own one-test family.
- Claim-tier classification per SPEC.md §8 (Strong / Moderate / Weak-or-inconclusive).

Output: `RESULTS.md` with every p-value, effect size, and CI plus the per-task means table.

---

## Reproducibility

Everything needed to reproduce the study end-to-end:

- This `benchmark/` directory at git tag `benchmark-prereg-v1`.
- The pre-registration document (`.planning/benchmark/PRE-REGISTRATION-DRAFT.md`).
- The signed k-decision addendum tag (`benchmark-prereg-v1.k-decision`).
- An Anthropic API key with rate-limit headroom for ~5 concurrent sessions.
- ~$2,500 budget if running the full pilot + formal + confirmatory sequence.
- ~80–120 person-hours of tagger time.
- SWE-Bench-Verified harness installed (`pip install swebench` or per the official instructions at <https://github.com/princeton-nlp/SWE-bench>).

Anyone with the above reproduces the result. SWE-Bench tasks are evaluated by the official harness, ensuring third-party verifiability. Custom tasks (T7–T10) have rule-based assertion checklists shipped with this repository.

---

## What is NOT in this benchmark

Explicit non-investments (per the source-doc principle "explicit non-investments with rationale"):

- **No LLM-as-judge.** Adding one would inflate apparent effect sizes via judge bias toward the protocol they were prompted about. Manual tagging with inter-rater κ ≥ 0.7 is the principled alternative.
- **No N > 10 tasks.** Tagging cost scales linearly; N=20 = ~160 person-hours.
- **No subjective metrics.** Drift rate, task success, steps-to-success, tool-use refusal are all defined operationally.
- **No comparison against MemGPT / Letta / etc.** That is a capability-comparison study, separate from the drift-reduction validity test this benchmark answers.
- **No claim of generalization outside the tested envelope.** Findings apply to Sonnet 4.6 (and Opus 4.7 if confirmatory runs) on tasks shaped like the 10 in §1 at trajectory horizons ≥100 steps.

---

## File map

```
benchmark/
├── README.md                              (this file)
├── pyproject.toml                         (registers fern-mcp-server)
├── conditions.py                          (ClaudeAgentOptions for A/B/C)
├── placebo.py                             (4 fern_* noop tools with schema parity)
├── runner.py                              (async driver, asyncio.gather, manifest)
├── logger.py                              (JSONL writer, schema_version 1.0 LOCKED)
├── dry_run.py                             (single-case dry-run, ~$0.50)
├── tasks/
│   ├── __init__.py                        (TASK_REGISTRY dict)
│   ├── swebench/
│   │   ├── _common.py                     (issue_prompt, setup, check helpers)
│   │   ├── t01_django_11066.py
│   │   ├── t02_sympy_13865.py
│   │   ├── t03_astropy_14096.py
│   │   ├── t04_sklearn_26323.py
│   │   ├── t05_sphinx_11445.py
│   │   └── t06_pytest_11604.py
│   └── custom/
│       ├── t07_tiny_tq_multisession.py    (multi-session, sync/async/ID/retry decisions)
│       ├── t08_hcast_ml_pipeline.py       (model class + eval split commitments)
│       ├── t09_research_report.py         (non-coding: sourcing-bar, scope, structure)
│       └── t10_project_plan_yougile.py    (non-coding: scope-cut, sequencing, Yougile-mock)
└── analysis/
    ├── __init__.py
    └── analyze.py                         (Wilcoxon + Holm-Bonferroni + BCa bootstrap)
```

---

## Publish-null commitment

This commitment is binding, made at pre-registration tag time, irrespective of the eventual result:

1. **All raw JSONL trajectories** (anonymised where applicable) are published to the version-tagged GitHub release.
2. **All tagging worksheets** are published with their unblinding manifest.
3. **The analysis notebook** is published in the same release.
4. **`RESULTS.md`** is published with the eventual result — null, negative, or positive — written with the same rigor as a positive-result writeup.
5. If H1 is rejected (EDP increases drift), the finding is stated plainly in the project README at the same release.
6. If N=10 yields insufficient evidence, the framing is "insufficient evidence to claim a drift-reduction effect at the pre-registered effect size," not "EDP doesn't work."

The commitment is also encoded as a comment at the top of `runner.py`.

---

## References

- `.planning/benchmark/SPEC.md` — authoritative benchmark specification (~4,200 words)
- `.planning/benchmark/PRE-REGISTRATION-DRAFT.md` — pre-registration document (~2,000 words)
- `.planning/research/benchmark-methodology.md` — design rationale (3,127 words)
- `.planning/research/benchmark-sdk-research.md` — Claude Agent SDK capability research
- `.planning/research/strategic-synthesis-2026-05-25.md` — strategic context
- [SWE-Bench-Verified — princeton-nlp HF dataset](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
- [Anthropic Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Anthropic prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [On Randomness in Agentic Evals — arXiv:2602.07150](https://arxiv.org/abs/2602.07150)

---

## License

MIT, matching the EDP main package.
