"""Human-readable outputs: promos.html (visual), promos.md (text report) and promos.csv (spreadsheet).

    python -m promo_finder.report outputs/<show>/promos.json     # rebuild the reports from an existing run
"""
from __future__ import annotations

import csv
from pathlib import Path


def seg_str(p: dict) -> str:
    return " + ".join(f"E{s['episode']:02d} {s['start_ts']}–{s['end_ts']}" for s in p["segments"])


def write_reports(r: dict, out: Path, top_n: int = 25) -> None:
    from .html_report import write_html
    write_html(r, out)
    promos = r["promos"]
    st = r["stats"]
    prof = r["profile"]
    L = [f"# Promo picks — {r['show']}", "",
         f"- Generated: {r['generated_at']} · mode: **{r['mode']}** · models used: `{', '.join(r.get('models_used') or [str(r['model'])])}`",
         f"- Genre playbook: **{prof['primary_genre']}** (+ {prof['secondary_genre'] or '—'}) — {prof['genre_reason']}",
         f"- Premise: {prof['premise']}",
         f"- {r['episodes']} episodes · {len(promos)} promos ({sum(p['type'] == 'stitched' for p in promos)} stitched) · "
         f"{len(r['rejected'])} candidates rejected",
         f"- Tokens: raw script ≈ {st['raw_tokens_est']:,} → compact beat sheet ≈ {st['beat_sheet_tokens_est']:,}; "
         f"a full uncached run costs ≈ {st.get('full_run_input_tokens', 0):,} in / {st.get('full_run_output_tokens', 0):,} out "
         f"tokens; this run: {st['llm_calls']} fresh + {st['llm_cached_calls']} cached calls · {st['seconds']}s",
         *( [f"- ⚠️ No LLM answer (quota) for episodes {st['episodes_rules_fallback']}: their promos are rule-based. "
              "Re-run later to finish them; finished parts are cached."] if st.get("episodes_rules_fallback") else []),
         "", "## Post these first", "",
         *( [f"_Editor strategy: {r['editor_notes']}_", ""] if r.get("editor_notes") else []),
         "Ranks 1-10 come from an LLM head-to-head review of the 20 highest-scoring promos; the rest follow the "
         "playbook score with a diversity penalty (no back-to-back repeats of an archetype or episode).", "",
         "| # | Score | Promo | Segments | Len | Archetype | Hook / Cliff / Standalone |",
         "|---|---|---|---|---|---|---|"]
    for p in promos[:top_n]:
        s = p["scores"]
        L.append(f"| {p['rank']} | {s['final']} | {p['title']} ({p['type']}{', rules' if p['source'] == 'rules' else ''}) | {seg_str(p)} | {p['duration']:.0f}s | "
                 f"{p['archetype_name']} | {s['hook']}/{s['cliffhanger']}/{s['standalone']} |")
    L += ["", "## Details (posting order)", ""]
    for p in promos:
        s = p["scores"]
        L += [f"### {p['rank']}. {p['title']} — {s['final']}",
              f"- **Segments:** {seg_str(p)} ({p['duration']:.1f}s, {p['type']}, id `{p['id']}`)",
              f"- **Hook (0–3s):** {p['hook']}",
              f"- **Cliffhanger:** {p['cliffhanger']}",
              f"- **Why it works:** {p['why_it_works']}",
              *( [f"- **Why post it #{p['rank']}:** {p['why_post_first']}"] if p.get("why_post_first") else []),
              f"- **Archetype:** {p['archetype_name']} · scores hook {s['hook']}, cliffhanger {s['cliffhanger']}, "
              f"standalone {s['standalone']} ({'of 100' if r.get('score_scale') == 100 else 'of 5'})",
              *( ["- **Checklist (0-10):** " + ", ".join(f"{k} {v}" for k, v in s["rubric"].items())]
                 if s.get("rubric") else [])]
        if p.get("standalone_issue"):
            L.append(f"- **New-viewer gap:** {p['standalone_issue']}")
        if p.get("warnings"):
            L.append("- **Checks:** " + "; ".join(p["warnings"]))
        if p.get("script"):
            L += ["", "<details><summary>Promo script (what the viewer sees and hears)</summary>", "", "```",
                  *p["script"], "```", "", "</details>"]
        L.append("")
    if r["rejected"]:
        L += ["## Rejected by the judge", ""]
        for x in r["rejected"]:
            if "candidate" in x:
                c, j = x["candidate"], x["judge"]
                L.append(f"- `{c['id']}` {c['start']:.1f}–{c['end']:.1f}s: {j.get('why_it_works', '')}")
            else:
                L.append(f"- stitched '{x['stitched'].get('title')}': {x.get('reason')}")
    (out / "promos.md").write_text("\n".join(L), encoding="utf-8")

    with open(out / "promos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "type", "title", "segments", "duration_s", "hook", "cliffhanger", "why_it_works",
                    "archetype", "hook_score", "cliffhanger_score", "standalone_score", "final_score", "warnings"])
        for p in promos:
            s = p["scores"]
            w.writerow([p["rank"], p["id"], p["type"], p["title"], seg_str(p), p["duration"], p["hook"], p["cliffhanger"],
                        p["why_it_works"], p["archetype_name"], s["hook"], s["cliffhanger"], s["standalone"], s["final"],
                        " | ".join(p.get("warnings", []))])


if __name__ == "__main__":
    import json
    import sys
    src = Path(sys.argv[1])
    write_reports(json.loads(src.read_text(encoding="utf-8")), src.parent)
    print(f"rebuilt {src.parent}/promos.html, promos.md, promos.csv")
