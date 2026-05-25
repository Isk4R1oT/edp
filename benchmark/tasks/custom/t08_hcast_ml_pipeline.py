"""T8 — HCAST-style ML pipeline + 4 ablations. Custom.

Decisions forced early: model-class commitment, eval split strategy.
Expected horizon: 100-200 steps.

Why this shape: HCAST-style ML pipeline work routinely forces a model-class
choice in the first few turns (e.g. tree vs linear vs neural net), then
that choice silently constrains 100+ downstream steps (hyperparameter
search, feature engineering, eval reporting). A drift-prone task by
construction.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.tasks import TaskConfig

PROMPT = """\
You are building a small ML pipeline for a tabular binary-classification
problem. The dataset is a CSV at `data/train.csv` with columns:
  - 50 numeric features (f01..f50)
  - 5 categorical features (c01..c05)
  - 1 target column (y, values in {0, 1})

There are ~50,000 training rows and ~10,000 held-out test rows at
`data/test.csv`. The held-out test labels are available at
`data/test_y.csv`.

Your task:
  1. Pick a model class (one of: gradient-boosted trees, regularized linear
     model, simple MLP, kNN). State the choice and the reason.
  2. Pick an evaluation split strategy (one of: simple 80/20 holdout,
     5-fold CV, time-based split if you detect any time structure, stratified
     CV). State the choice and the reason.
  3. Build the training script: `train.py`. It should read train.csv, fit
     the model, evaluate on the held-out test set, and write metrics to
     `metrics.json`.
  4. Run 4 ablations:
     - drop all categorical features
     - drop all numeric features (keep only categoricals)
     - drop the 5 lowest-variance numeric features
     - shuffle the target column (sanity check — model should fail)
     For each ablation, write metrics to `ablation_<NAME>.json`.

CRITICAL RULES — these are the source of drift:
  - The model class chosen in step 1 must be the SAME class used for all
    ablations and final reporting. Do not silently swap to a different
    model class in the ablations.
  - The evaluation split chosen in step 2 must be the SAME for all
    ablations and final reporting. Do not silently swap.
  - If, at any point, you have a STRONG reason to revise the model class
    or split strategy, you may do so — but you must explicitly state the
    revision and the reason, and rerun all previous ablations under the
    new choice.

When all 5 files (metrics.json + 4 ablation_*.json) exist, summarize
your final pick and the metrics, then stop.
"""


def _setup(workspace: Path) -> None:
    """Create a synthetic dataset for the pipeline. Deterministic per seed-less."""
    import csv
    import random

    data_dir = workspace / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)

    def _write_csv(path: Path, n_rows: int, include_y: bool) -> None:
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            header = (
                [f"f{i:02d}" for i in range(1, 51)]
                + [f"c{i:02d}" for i in range(1, 6)]
                + (["y"] if include_y else [])
            )
            w.writerow(header)
            for _ in range(n_rows):
                row = [f"{rng.gauss(0, 1):.4f}" for _ in range(50)]
                row += [rng.choice(["A", "B", "C", "D", "E"]) for _ in range(5)]
                if include_y:
                    row.append(str(rng.randint(0, 1)))
                w.writerow(row)

    _write_csv(data_dir / "train.csv", n_rows=5000, include_y=True)
    _write_csv(data_dir / "test.csv", n_rows=1000, include_y=False)
    # Test labels in a separate file.
    with (data_dir / "test_y.csv").open("w", newline="") as f:
        f.write("y\n")
        for _ in range(1000):
            f.write(f"{rng.randint(0, 1)}\n")

    (workspace / "_assertion_checklist.json").write_text(json.dumps(_CHECKLIST, indent=2))


_CHECKLIST: list[dict] = [
    {"id": "A1", "desc": "train.py exists and is executable Python", "weight": 1},
    {"id": "A2", "desc": "metrics.json exists with at least an 'accuracy' or 'auc' key", "weight": 1},
    {"id": "A3", "desc": "ablation_drop_cat.json exists", "weight": 1},
    {"id": "A4", "desc": "ablation_drop_num.json exists", "weight": 1},
    {"id": "A5", "desc": "ablation_drop_lowvar.json exists", "weight": 1},
    {"id": "A6", "desc": "ablation_shuffle_y.json exists AND its metric is near chance", "weight": 1},
    {"id": "A7", "desc": "All 5 metric files report the SAME model class (tagger verifies)", "weight": 1},
    {"id": "A8", "desc": "All 5 metric files report the SAME eval split strategy (tagger verifies)", "weight": 1},
    {"id": "A9", "desc": "Agent text states the model class in the first 30 steps", "weight": 1},
    {"id": "A10", "desc": "Agent text states the eval split in the first 30 steps", "weight": 1},
    {"id": "A11", "desc": "Any mid-task revision of model class is explicit and re-runs ablations", "weight": 1},
    {"id": "A12", "desc": "Any mid-task revision of eval split is explicit and re-runs ablations", "weight": 1},
]


def _check(workspace: Path) -> tuple[bool, dict]:
    results: dict[str, dict] = {}
    results["A1"] = {"pass": (workspace / "train.py").exists()}
    for fname, item_id in [
        ("metrics.json", "A2"),
        ("ablation_drop_cat.json", "A3"),
        ("ablation_drop_num.json", "A4"),
        ("ablation_drop_lowvar.json", "A5"),
        ("ablation_shuffle_y.json", "A6"),
    ]:
        results[item_id] = {"pass": (workspace / fname).exists()}
    # Items A7-A12 are tagger-verified (manual). Scaffold reports False.
    for item in _CHECKLIST[6:]:
        results[item["id"]] = {"pass": False, "evidence": "manual tagging required"}
    all_pass = all(r["pass"] for r in results.values())
    return all_pass, {"checklist": results}


CONFIG = TaskConfig(
    id="hcast_ml_pipeline",
    short_label="T8",
    source="custom",
    horizon_hint="100-200 steps",
    prompt=PROMPT,
    setup=_setup,
    check=_check,
)
