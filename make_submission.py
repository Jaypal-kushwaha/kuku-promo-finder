#!/usr/bin/env python3
"""Package everything for the Kuku submission form into ./submission/ (upload that folder to Google Drive).

    .venv/bin/python make_submission.py                       # uses every run in outputs/
    .venv/bin/python make_submission.py --doc solution.pdf    # also copies your solution doc

Creates:
  submission/
    raw_outputs/<run>/...        unedited outputs of each run (promos.md/csv/json, candidates, llm_raw/, quality_report)
    raw_outputs.zip              the same, zipped (handy as a single Drive link)
    Solution_Doc.pdf             if --doc is given (brief: PDF, max 2 pages)
    SUBMISSION_CHECKLIST.md      what goes in each field of the form
"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CHECKLIST = """# Kuku AI Generalist: submission checklist (Problem 1: Find the Promos)

The form asks for: name, roll number, branch, the problem chosen, and the links below.
**Every link must open for anyone who has it** (Drive: Share → General access → "Anyone with the link" → Viewer).

| Form item | Required | What to give | Status |
|---|---|---|---|
| Problem chosen | yes | Problem 1: Find the Promos (Ads) | |
| Solution doc | yes | PDF, max 2 pages → `Solution_Doc.pdf` in this Drive folder (share the file link) | {doc} |
| Prototype link | yes | GitHub repo URL (README has run steps) and/or Streamlit Cloud app URL | |
| Raw outputs | yes | Drive link to `raw_outputs/` (or `raw_outputs.zip`): unedited outputs on the FULL input pack | {runs} |
| Walkthrough video | optional, recommended | ≤ 3 min screen recording in your own voice (Loom / unlisted YouTube / Drive) | |

## Solution doc must cover (per the brief)
- which problem and why · assumptions made · how the solution works
- how it scales to every show (cost per show, time, human in the loop)
- how you know it's good, **including where it fails**
- which AI tools you used and **one place where they got it wrong**

## Before submitting
- [ ] Final run done on all 50 episodes (`raw_outputs/` has promos.md, promos.csv, promos.json, llm_raw/)
- [ ] Raw outputs are UNEDITED (don't hand-fix them; describe problems in the doc instead)
- [ ] Every link opened in an incognito window
- [ ] The repo does NOT contain the input pack (Kuku confidential; .gitignore excludes it)
- [ ] Submitted before the 48-hour deadline
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", help="path to your solution PDF")
    ap.add_argument("--out", default=str(ROOT / "submission"))
    ap.add_argument("--runs", nargs="*", help="output folder names to include (default: all in outputs/)")
    a = ap.parse_args()
    out = Path(a.out)
    raw = out / "raw_outputs"
    if raw.exists():
        shutil.rmtree(raw)
    raw.mkdir(parents=True)
    runs = [p.parent for p in sorted((ROOT / "outputs").glob("*/promos.json")) if not p.parent.name.startswith("ui_")]
    if a.runs:
        runs = [r for r in runs if r.name in a.runs]
    for r in runs:
        shutil.copytree(r, raw / r.name)
    (raw / "README.txt").write_text(
        "Unedited outputs of the promo finder on the full 50-episode input pack.\n"
        "Start with promos.html (open in a browser: top 10 as cards). promos.md = same as text; promos.csv = same as a sheet; promos.json = everything incl. scores, "
        "checks and token usage; candidates_rules.json = rule-based windows before the LLM; llm_raw/ = every prompt "
        "and raw model response (or a replay note).\nfull_run_v1/ = the complete AI run on all 50 episodes. "
        "rules_only/ = the zero-token baseline used for comparison.\n")
    shutil.make_archive(str(out / "raw_outputs"), "zip", raw)
    doc_status = "missing"
    if a.doc:
        shutil.copy(a.doc, out / "Solution_Doc.pdf")
        doc_status = "copied"
    (out / "SUBMISSION_CHECKLIST.md").write_text(
        CHECKLIST.format(doc=doc_status, runs=", ".join(r.name for r in runs) or "NO RUNS FOUND"), encoding="utf-8")
    print(f"Packed {len(runs)} run(s) into {out}/")
    for r in runs:
        print("  -", r.name)
    print(f"Next: upload the folder {out} to Google Drive and set sharing to 'Anyone with the link'.")


if __name__ == "__main__":
    main()
