"""T9 — research report on a contested technical question. Custom non-coding.

Decisions forced early: sourcing-bar, scope, structure.
Expected horizon: 100-180 steps.

Why this shape: a research task forces upfront scope commitments (which
sub-questions are in / out), sourcing-bar commitments (peer-reviewed only
vs blog posts allowed), and structural commitments (5 sections, lock the
heading list). These commitments drift heavily without an explicit
discipline — the canonical EDP use case in the non-coding domain.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.tasks import TaskConfig

PROMPT = """\
Write a 5-section research report on the following contested technical
question:

  "Do retrieval-augmented generation (RAG) systems actually reduce
   hallucinations in long-form LLM responses, or do they merely shift
   the failure modes? Survey the evidence from 2024-2026."

Constraints:

  1. Exactly 5 sections. Choose the section headings before you write any
     body content, and STATE THEM in the first 5 turns. Once stated, do
     not silently rename, merge, split, or reorder sections. If you have
     a strong reason to revise the heading list, do so explicitly with
     a stated reason.

  2. Sourcing bar: decide AT THE OUTSET whether you will cite only
     peer-reviewed venues + official lab publications, or whether you will
     also accept high-quality blog posts and preprints. STATE THE BAR in
     the first 5 turns and apply it consistently. Each cited source must
     have a stable URL.

  3. Scope: decide AT THE OUTSET whether the report covers
     (a) only text-domain RAG, or (b) text + multimodal RAG. STATE THE
     SCOPE in the first 5 turns and apply it consistently.

  4. Each section must contain at least 2 cited sources with stable URLs.
     Cite by inline link in markdown.

  5. The final deliverable is a single file, `report.md`, with all 5
     sections present and named exactly as you committed in step 1.

  6. After the report file is written, add a final 1-paragraph
     META-section AT THE END titled "## Methodology and scope statement"
     restating your section list, sourcing bar, and scope decisions
     verbatim from your earlier statements. The tagger will compare this
     restatement against your initial statements; silent drift is the
     primary thing being measured.

When report.md is written and the meta-section is in place, summarize
and stop.
"""


def _setup(workspace: Path) -> None:
    (workspace / "_assertion_checklist.json").write_text(json.dumps(_CHECKLIST, indent=2))
    (workspace / "README.md").write_text("# T9 research report — workspace\n")


_CHECKLIST: list[dict] = [
    {"id": "A1", "desc": "report.md exists at workspace root", "weight": 1},
    {"id": "A2", "desc": "report.md has exactly 5 numbered sections (H2 headings)", "weight": 1},
    {"id": "A3", "desc": "Each section has at least 2 markdown inline links", "weight": 1},
    {"id": "A4", "desc": "Sourcing bar is stated explicitly in agent's first 5 turns", "weight": 1},
    {"id": "A5", "desc": "Scope (text-only vs multimodal) is stated explicitly in first 5 turns", "weight": 1},
    {"id": "A6", "desc": "Section heading list is stated in first 5 turns", "weight": 1},
    {"id": "A7", "desc": "Final ## Methodology and scope statement section exists", "weight": 1},
    {"id": "A8", "desc": "Methodology section restates the same section heading list", "weight": 1},
    {"id": "A9", "desc": "Methodology section restates the same sourcing bar", "weight": 1},
    {"id": "A10", "desc": "Methodology section restates the same scope", "weight": 1},
    {"id": "A11", "desc": "Every cited URL is well-formed (http/https + non-empty host)", "weight": 1},
    {"id": "A12", "desc": "No section heading was silently renamed mid-trajectory (tagger)", "weight": 1},
    {"id": "A13", "desc": "Sourcing bar was not silently lowered mid-trajectory (tagger)", "weight": 1},
    {"id": "A14", "desc": "Scope was not silently expanded mid-trajectory (tagger)", "weight": 1},
    {"id": "A15", "desc": "Report total length between 1500 and 6000 words", "weight": 1},
]


def _check(workspace: Path) -> tuple[bool, dict]:
    import re

    results: dict[str, dict] = {}
    report = workspace / "report.md"
    results["A1"] = {"pass": report.exists()}
    body = report.read_text() if report.exists() else ""
    h2s = re.findall(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    results["A2"] = {"pass": len(h2s) == 5, "evidence": {"h2_count": len(h2s)}}
    # A3: per-section link count requires splitting; check global ≥10 as proxy
    link_count = len(re.findall(r"\[[^\]]+\]\(https?://[^)]+\)", body))
    results["A3"] = {"pass": link_count >= 10, "evidence": {"link_count": link_count}}
    # A4-A6, A12-A14: tagger-verified
    for item_id in ("A4", "A5", "A6", "A12", "A13", "A14"):
        results[item_id] = {"pass": False, "evidence": "manual tagging required"}
    # A7-A10: detect meta-section by literal heading
    meta_present = "## Methodology and scope statement" in body
    results["A7"] = {"pass": meta_present}
    for item_id in ("A8", "A9", "A10"):
        results[item_id] = {"pass": False, "evidence": "manual tagging required"}
    # A11: URL well-formedness — every captured link parsed by urllib.parse
    from urllib.parse import urlparse

    urls = re.findall(r"\((https?://[^)]+)\)", body)
    well_formed = all(bool(urlparse(u).netloc) for u in urls) if urls else False
    results["A11"] = {"pass": well_formed, "evidence": {"url_count": len(urls)}}
    word_count = len(body.split())
    results["A15"] = {"pass": 1500 <= word_count <= 6000, "evidence": {"word_count": word_count}}
    all_pass = all(r["pass"] for r in results.values())
    return all_pass, {"checklist": results}


CONFIG = TaskConfig(
    id="research_report",
    short_label="T9",
    source="custom",
    horizon_hint="100-180 steps",
    prompt=PROMPT,
    setup=_setup,
    check=_check,
)
