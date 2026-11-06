#!/usr/bin/env python3
"""Quality report for a promo run — 'where does the tool pick badly?'

    python eval/quality.py outputs/<show>/promos.json [--gold eval/gold.yaml] [--compare other_run/promos.json]
                           [--ratings eval/ratings.yaml]

Writes quality_report.md next to promos.json. Measures:
  1. Automatic checks: duration, mid-sentence opens, visual-only opens, trims/extensions
  2. Score inflation: how often the LLM gives 5/5 (saturation = weak discrimination)
  3. What the LLM changed vs the rule windows (boundary shifts, rejections)
  4. Gold-set recall: did we find the moments a human editor marked?  (needs --gold)
  5. Human ratings of the top picks: usable / needs-trim / bad          (needs --ratings)
  6. Stability: top-10 overlap with another run / another model        (needs --compare)
"""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import yaml


def overlap_sec(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("promos")
    ap.add_argument("--gold")
    ap.add_argument("--compare")
    ap.add_argument("--ratings")
    a = ap.parse_args()
    r = json.loads(Path(a.promos).read_text())
    P = r["promos"]
    L = [f"# Quality report — {r['show']}", "", f"Run: {r['generated_at']} · mode {r['mode']} · models "
         f"{', '.join(r.get('models_used') or [str(r.get('model'))])} · {len(P)} promos", ""]

    # 1 automatic checks
    durs = [p["duration"] for p in P]
    wc = Counter()
    for p in P:
        for w in p.get("warnings", []):
            key = ("too long → trimmed" if w.startswith("too long") else "too short → extended" if w.startswith("too short")
                   else "opens mid-sentence" if "mid-sentence" in w else "visual-only open" if "visual only" in w
                   else "snapped to clean cut" if "snapped" in w else "invalid/fallback beats" if "fell back" in w or "out of range" in w
                   else w[:50])
            wc[key] += 1
    L += ["## 1. Automatic checks", "",
          f"- Duration: min {min(durs):.0f}s · median {statistics.median(durs):.0f}s · max {max(durs):.0f}s "
          f"(target 20–60s; {sum(20 <= d <= 60.5 for d in durs)}/{len(durs)} in range after fixes)",
          f"- Episodes with ≥1 promo: {len({s['episode'] for p in P for s in p['segments']})}/{r['episodes']}"]
    L += [f"- {k}: {v}" for k, v in wc.most_common()] + [""]

    # 2 score inflation
    if r["mode"] == "llm":
        L += ["## 2. LLM score saturation", ""]
        for dim in ("hook", "cliffhanger", "standalone"):
            c = Counter(p["scores"][dim] for p in P)
            L.append(f"- {dim}: " + " · ".join(f"{k}→{c.get(k, 0)}" for k in (5, 4, 3, 2, 1))
                     + f"  ({100 * c.get(5, 0) / len(P):.0f}% are 5/5)")
        perfect = sum(all(p["scores"][d] == 5 for d in ("hook", "cliffhanger", "standalone")) for p in P)
        L += [f"- Promos scored 5/5/5: {perfect}/{len(P)} → per-clip scores alone cannot rank; "
              "this is why the top 10 comes from a head-to-head editor review.", ""]

        # 3 LLM vs rules
        singles = [p for p in P if p["type"] == "single" and "rule_window" in p]
        ds = [abs(p["segments"][0]["start"] - p["rule_window"]["start"]) for p in singles]
        de = [abs(p["segments"][0]["end"] - p["rule_window"]["end"]) for p in singles]
        moved = sum(x > 1 or y > 1 for x, y in zip(ds, de))
        n_cand = len(singles) + sum(1 for x in r["rejected"] if "candidate" in x)
        L += ["## 3. What the LLM judge changed vs the rule windows", "",
              f"- Rule candidates judged: ~{n_cand}; rejected by judge: {sum(1 for x in r['rejected'] if 'candidate' in x)}",
              f"- Kept promos whose cut moved >1s: {moved}/{len(singles)} (median start shift {statistics.median(ds) if ds else 0:.1f}s, "
              f"end shift {statistics.median(de) if de else 0:.1f}s)", ""]

    # 4 gold recall
    if a.gold and Path(a.gold).exists():
        gold = yaml.safe_load(Path(a.gold).read_text()) or []
        hits, rows = 0, []
        for g in gold:
            g0, g1 = _sec(g["start"]), _sec(g["end"])
            best = None
            for p in P:
                for s in p["segments"]:
                    if s["episode"] == g["episode"]:
                        ov = overlap_sec(g0, g1, s["start"], s["end"]) / max(1e-6, g1 - g0)
                        if ov > 0 and (best is None or ov > best[0]):
                            best = (ov, p["rank"], p["title"])
            hit = best is not None and best[0] >= 0.5
            hits += hit
            rows.append(f"| E{g['episode']} {g['start']}–{g['end']} | {g.get('note', '')} | "
                        + (f"{'✅' if hit else '⚠️ partial'} #{best[1]} {best[2]} ({best[0]:.0%})" if best else "❌ missed") + " |")
        L += ["## 4. Gold-set recall (human-marked promo moments)", "",
              f"**{hits}/{len(gold)} found** (≥50% of the marked moment inside a promo)", "",
              "| Gold moment | Note | Best match |", "|---|---|---|", *rows, ""]

    # 5 human ratings
    if a.ratings and Path(a.ratings).exists():
        rat = yaml.safe_load(Path(a.ratings).read_text()) or {}
        c = Counter(rat.values())
        L += ["## 5. Human ratings of top picks", "",
              " · ".join(f"{k}: {v}" for k, v in c.most_common()) + f"  (of {len(rat)} rated)", ""]
        for pid, v in rat.items():
            p = next((x for x in P if x["id"] == pid), None)
            if p:
                L.append(f"- #{p['rank']} {p['title']} → **{v}**")
        L.append("")

    # 6 stability
    if a.compare and Path(a.compare).exists():
        o = json.loads(Path(a.compare).read_text())["promos"]

        def key(p):
            s = p["segments"][0]
            return s["episode"], s["start"], s["end"]

        def same(p, q):
            if len(p["segments"]) != 1 or len(q["segments"]) != 1:
                return False
            (e1, a0, a1), (e2, b0, b1) = key(p), key(q)
            return e1 == e2 and overlap_sec(a0, a1, b0, b1) > 0.5 * min(a1 - a0, b1 - b0)

        for k in (10, 25):
            hit = sum(any(same(p, q) for q in o[:k]) for p in P[:k])
            L.append(f"- Top-{k} overlap with {a.compare}: {hit}/{k}")
        L.append("")

    out = Path(a.promos).with_name("quality_report.md")
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nwrote {out}")


def _sec(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    m, s = str(ts).split(":")
    return int(m) * 60 + float(s)


if __name__ == "__main__":
    main()
