"""Post-run analysis — Wilcoxon signed-rank + BCa bootstrap CI.

Run after all trajectories are tagged. Inputs:
  - benchmark/runs/<run_id>/manifest.jsonl
  - benchmark/tagging/<trajectory_id>.tagging.json
Outputs:
  - benchmark/analysis/RESULTS.md
  - benchmark/analysis/figures/*.png
"""
