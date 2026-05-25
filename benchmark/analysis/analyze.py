"""Wilcoxon signed-rank + Holm-Bonferroni + BCa bootstrap analysis.

Implements SPEC.md §8 exactly. Reads:
  - <runs_dir>/manifest.jsonl                   (trajectory_id → task/condition/seed)
  - <runs_dir>/<trajectory_id>/<trajectory_id>.summary.json  (mechanical metrics)
  - <tagging_dir>/<trajectory_id>.tagging.json  (manual drift / negative tags)

Per-task mean is computed by averaging over k seeds per condition. The N=10
paired observations per planned comparison are the per-task means.

This is a SCAFFOLD: it implements the exact statistical pipeline, but uses
synthetic data when real tagging files are missing so the analysis can be
dry-run end-to-end. Real numbers require completed runs + tagging.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats


def _load_manifest(manifest_path: Path) -> list[dict]:
    entries: list[dict] = []
    if not manifest_path.exists():
        return entries
    for line in manifest_path.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _load_summary(runs_dir: Path, trajectory_id: str) -> Optional[dict]:
    path = runs_dir / trajectory_id / f"{trajectory_id}.summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_tagging(tagging_dir: Path, trajectory_id: str) -> Optional[dict]:
    path = tagging_dir / f"{trajectory_id}.tagging.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _drift_rate_from_tagging(tagging: dict) -> float:
    """Per SPEC.md §5.2: violations / (decisions × max(1, steps_after_30/100))."""
    decisions = len(tagging.get("decisions_made_before_step_30", []))
    violations = len(tagging.get("violations_after_step_30", []))
    steps_to_success = tagging.get("outcome", {}).get("steps_to_success") or 0
    steps_after_30 = max(0, steps_to_success - 30)
    if decisions == 0:
        return 0.0
    denom = decisions * max(1.0, steps_after_30 / 100.0)
    return violations / denom


def _aggregate_per_task(
    manifest_entries: list[dict],
    runs_dir: Path,
    tagging_dir: Path,
) -> dict[tuple[str, str], dict[str, float]]:
    """Returns: {(task_id, condition): {drift_rate_mean, task_success_mean, steps_mean}}."""
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for entry in manifest_entries:
        traj_id = entry["trajectory_id"]
        task_id = entry["task_id"]
        cond = entry["condition"]
        summary = _load_summary(runs_dir, traj_id)
        tagging = _load_tagging(tagging_dir, traj_id)
        if summary is None:
            continue
        drift = _drift_rate_from_tagging(tagging) if tagging else float("nan")
        task_success = (
            tagging.get("outcome", {}).get("task_success")
            if tagging else summary.get("task_success")
        )
        steps_to_success = (
            tagging.get("outcome", {}).get("steps_to_success")
            if tagging else summary.get("num_turns")
        )
        by_key[(task_id, cond)].append(
            {
                "drift_rate": drift,
                "task_success": float(bool(task_success)) if task_success is not None else float("nan"),
                "steps_to_success": float(steps_to_success) if steps_to_success is not None else float("nan"),
            }
        )

    out: dict[tuple[str, str], dict[str, float]] = {}
    for key, runs in by_key.items():
        drifts = [r["drift_rate"] for r in runs if not np.isnan(r["drift_rate"])]
        succ = [r["task_success"] for r in runs if not np.isnan(r["task_success"])]
        steps = [r["steps_to_success"] for r in runs if not np.isnan(r["steps_to_success"])]
        out[key] = {
            "drift_rate_mean": float(np.mean(drifts)) if drifts else float("nan"),
            "task_success_mean": float(np.mean(succ)) if succ else float("nan"),
            "steps_mean": float(np.mean(steps)) if steps else float("nan"),
            "n_seeds": len(runs),
        }
    return out


def _paired_deltas(
    per_task: dict[tuple[str, str], dict[str, float]],
    *,
    metric: str,
    cond_a: str,
    cond_b: str,
) -> tuple[list[float], list[str]]:
    """Returns (deltas, task_ids) where delta = per_task[(t, cond_a)] - per_task[(t, cond_b)]."""
    task_ids = sorted({k[0] for k in per_task})
    deltas: list[float] = []
    valid_tasks: list[str] = []
    for t in task_ids:
        a = per_task.get((t, cond_a), {}).get(metric, float("nan"))
        b = per_task.get((t, cond_b), {}).get(metric, float("nan"))
        if not (np.isnan(a) or np.isnan(b)):
            deltas.append(a - b)
            valid_tasks.append(t)
    return deltas, valid_tasks


def _wilcoxon(deltas: list[float]) -> tuple[float, float]:
    """Two-tailed Wilcoxon signed-rank. Returns (statistic, p-value).

    For N<6 the test is unreliable; scipy returns p but caller should
    flag in RESULTS.md.
    """
    if len(deltas) < 2 or all(d == 0 for d in deltas):
        return float("nan"), float("nan")
    result = stats.wilcoxon(deltas, alternative="two-sided", zero_method="wilcox")
    return float(result.statistic), float(result.pvalue)


def _bca_bootstrap_median(deltas: list[float], *, n_resamples: int = 10_000) -> dict:
    """95% BCa bootstrap CI on the median of paired deltas. Per SPEC.md §8."""
    if len(deltas) < 2:
        return {"low": float("nan"), "high": float("nan"), "median": float("nan")}
    data = (np.asarray(deltas, dtype=float),)
    res = stats.bootstrap(
        data,
        statistic=np.median,
        method="BCa",
        n_resamples=n_resamples,
        random_state=42,
        confidence_level=0.95,
    )
    return {
        "low": float(res.confidence_interval.low),
        "high": float(res.confidence_interval.high),
        "median": float(np.median(deltas)),
    }


def _holm_bonferroni(pvalues: list[float], *, alpha: float = 0.05) -> list[bool]:
    """Holm-Bonferroni correction. Returns reject-null booleans in original order."""
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    reject = [False] * m
    for rank, idx in enumerate(order):
        threshold = alpha / (m - rank)
        if pvalues[idx] <= threshold:
            reject[idx] = True
        else:
            break
    return reject


def run_analysis(*, runs_dir: Path, tagging_dir: Path, out_path: Path) -> None:
    """Top-level analysis driver. Writes RESULTS.md per SPEC.md §0."""
    manifest = _load_manifest(runs_dir / "manifest.jsonl")
    per_task = _aggregate_per_task(manifest, runs_dir, tagging_dir)

    # Primary comparisons
    comparisons = [
        ("H1", "drift_rate_mean", "B", "C"),
        ("H2", "task_success_mean", "B", "C"),
        ("H3", "steps_mean", "B", "C"),
    ]
    negative_control = ("H4", "drift_rate_mean", "A", "C")

    primary_results: list[dict] = []
    pvalues_primary: list[float] = []
    for label, metric, ca, cb in comparisons:
        deltas, tasks = _paired_deltas(per_task, metric=metric, cond_a=ca, cond_b=cb)
        stat, p = _wilcoxon(deltas)
        ci = _bca_bootstrap_median(deltas)
        primary_results.append({
            "label": label, "metric": metric, "cond_a": ca, "cond_b": cb,
            "n_paired": len(deltas), "tasks": tasks,
            "statistic": stat, "p_value": p, **ci,
        })
        pvalues_primary.append(p if not np.isnan(p) else 1.0)

    reject_primary = _holm_bonferroni(pvalues_primary)
    for r, rej in zip(primary_results, reject_primary, strict=True):
        r["reject_null_holm_bonferroni"] = bool(rej)

    # Negative control (its own family)
    label, metric, ca, cb = negative_control
    deltas_neg, tasks_neg = _paired_deltas(per_task, metric=metric, cond_a=ca, cond_b=cb)
    stat_neg, p_neg = _wilcoxon(deltas_neg)
    ci_neg = _bca_bootstrap_median(deltas_neg)
    neg_result = {
        "label": label, "metric": metric, "cond_a": ca, "cond_b": cb,
        "n_paired": len(deltas_neg), "tasks": tasks_neg,
        "statistic": stat_neg, "p_value": p_neg, **ci_neg,
        "reject_null_uncorrected": bool(p_neg <= 0.05) if not np.isnan(p_neg) else False,
    }

    # Write RESULTS.md
    lines: list[str] = []
    lines.append("# EDP benchmark — RESULTS\n")
    lines.append("> Generated by `benchmark/analysis/analyze.py`. Publish-null commitment honoured.\n")
    lines.append("\n## Primary tests (Wilcoxon signed-rank, two-tailed, Holm-Bonferroni)\n")
    for r in primary_results:
        lines.append(f"\n### {r['label']}: {r['metric']} — {r['cond_a']} vs {r['cond_b']}\n")
        lines.append(f"- Paired N: {r['n_paired']}")
        lines.append(f"- Median paired delta ({r['cond_a']} − {r['cond_b']}): {r['median']:.4f}")
        lines.append(f"- 95% BCa CI: [{r['low']:.4f}, {r['high']:.4f}]")
        lines.append(f"- Wilcoxon statistic: {r['statistic']:.3f}")
        lines.append(f"- p-value (uncorrected): {r['p_value']:.4f}")
        lines.append(f"- Reject null at α=0.05 (Holm-Bonferroni): {r['reject_null_holm_bonferroni']}")
    lines.append("\n## Negative control (its own family at α=0.05)\n")
    lines.append(f"### {neg_result['label']}: {neg_result['metric']} — {neg_result['cond_a']} vs {neg_result['cond_b']}\n")
    lines.append(f"- Paired N: {neg_result['n_paired']}")
    lines.append(f"- Median paired delta: {neg_result['median']:.4f}")
    lines.append(f"- 95% BCa CI: [{neg_result['low']:.4f}, {neg_result['high']:.4f}]")
    lines.append(f"- p-value: {neg_result['p_value']:.4f}")
    lines.append(f"- Reject null at α=0.05: {neg_result['reject_null_uncorrected']}")
    lines.append("\n## Per-task means\n")
    lines.append("| task | cond | drift_rate_mean | task_success_mean | steps_mean | n_seeds |")
    lines.append("|---|---|---|---|---|---|")
    for (t, c), m in sorted(per_task.items()):
        lines.append(
            f"| {t} | {c} | {m['drift_rate_mean']:.4f} | "
            f"{m['task_success_mean']:.3f} | {m['steps_mean']:.1f} | {int(m['n_seeds'])} |"
        )
    lines.append("\n## Pre-registered claim tier\n")
    # H1 drives the tier.
    h1 = primary_results[0]
    if h1["reject_null_holm_bonferroni"] and h1["low"] < 0 and abs(h1["median"]) >= 0.30:
        tier = "Strong"
    elif h1["reject_null_holm_bonferroni"] and h1["low"] < 0 and abs(h1["median"]) >= 0.15:
        tier = "Moderate"
    else:
        tier = "Weak / inconclusive"
    lines.append(f"- **{tier}** (per SPEC.md §8 claim tiers; honest framing in body above).")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"[analyze] wrote {out_path}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--runs-dir", type=Path, required=True)
    p.add_argument("--tagging-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("benchmark/analysis/RESULTS.md"))
    args = p.parse_args()
    run_analysis(runs_dir=args.runs_dir, tagging_dir=args.tagging_dir, out_path=args.out)


if __name__ == "__main__":
    main()
