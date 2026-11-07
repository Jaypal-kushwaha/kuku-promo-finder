"""promos.html — a visual, self-contained report: the top 10 as cards, the rest as a table.

Open it in any browser (double-click). No internet or extra files needed.
"""
from __future__ import annotations

import html
from pathlib import Path

CSS = """
:root{--bg:#f6f4f1;--card:#fff;--ink:#1d1b19;--muted:#6b665f;--line:#e7e2db;--accent:#c2410c;--accent-soft:#fdecdf;
--good:#15803d;--warn:#b45309;--chip:#f1ede7;--shadow:0 1px 2px rgba(0,0,0,.05),0 4px 14px rgba(0,0,0,.05)}
@media (prefers-color-scheme:dark){:root{--bg:#141210;--card:#1e1b18;--ink:#f1ece6;--muted:#a59e94;--line:#2f2a25;
--accent:#fb923c;--accent-soft:#3a2516;--good:#4ade80;--warn:#fbbf24;--chip:#2a2622;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 18px 60px}
header .eyebrow{color:var(--accent);font-weight:700;font-size:12px;letter-spacing:.12em;text-transform:uppercase}
header h1{font-size:30px;line-height:1.2;margin:4px 0 6px}
header p.premise{color:var(--muted);max-width:820px;margin:0 0 14px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 6px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;min-width:120px;box-shadow:var(--shadow)}
.stat b{display:block;font-size:22px;line-height:1.1}
.stat span{color:var(--muted);font-size:12.5px}
.note{background:var(--accent-soft);border-radius:10px;padding:10px 14px;margin:14px 0;font-size:14px}
h2{font-size:21px;margin:34px 0 4px}
.sub{color:var(--muted);margin:0 0 14px;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 16px 12px;box-shadow:var(--shadow);
display:flex;flex-direction:column;gap:8px;position:relative}
.card.first{border:2px solid var(--accent)}
.top{display:flex;gap:12px;align-items:flex-start}
.rank{flex:none;width:40px;height:40px;border-radius:12px;background:var(--accent);color:#fff;font-weight:800;font-size:18px;
display:grid;place-items:center}
.title{font-weight:700;font-size:16.5px;line-height:1.3}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.tag{background:var(--chip);border-radius:999px;padding:2px 9px;font-size:12px;color:var(--muted);white-space:nowrap}
.tag.stitch{background:var(--accent-soft);color:var(--accent);font-weight:600}
.segs{display:flex;flex-wrap:wrap;gap:6px}
.seg{font:600 13px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;border:1px solid var(--line);border-radius:8px;padding:3px 8px}
.row{font-size:14px}
.row .k{display:block;font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.why{border-top:1px dashed var(--line);padding-top:8px;font-size:14px}
.why b{color:var(--accent)}
.bars{display:grid;grid-template-columns:auto 1fr auto;gap:3px 8px;align-items:center;font-size:12px;color:var(--muted)}
.bar{height:6px;background:var(--chip);border-radius:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);border-radius:6px}
details{font-size:13px}
summary{cursor:pointer;color:var(--accent);font-weight:600}
pre{white-space:pre-wrap;background:var(--chip);border-radius:10px;padding:10px;font:12.5px/1.5 ui-monospace,Consolas,monospace;margin:8px 0 0;max-height:320px;overflow:auto}
.warn{font-size:12.5px;color:var(--warn)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:14px}
th{text-align:left;font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);padding:10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
td.mono{font:13px ui-monospace,Consolas,monospace;white-space:nowrap}
.tablewrap{overflow-x:auto}
.head{flex:1;min-width:0}
.score{flex:none;margin-left:auto;text-align:center;min-width:64px}
.score b{display:block;font-size:24px;line-height:1;color:var(--accent)}
.score span{font-size:11px;color:var(--muted)}
.pick{font-size:12.5px;font-weight:600;color:var(--good)}
.bars .w{font-size:11px;opacity:.75}
.how{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin:16px 0 4px;box-shadow:var(--shadow)}
.how h3{margin:0 0 6px;font-size:15px}
.how ol{margin:0;padding-left:20px;font-size:14px}
.how li{margin:3px 0}
.how .wts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
td.num{font-weight:700;color:var(--accent);white-space:nowrap}
footer{color:var(--muted);font-size:12.5px;margin-top:34px}
@media (max-width:520px){header h1{font-size:24px}.grid{grid-template-columns:1fr}}
@media print{body{background:#fff}.card{break-inside:avoid;box-shadow:none}details{display:none}}
"""


def _e(x) -> str:
    return html.escape(str(x or ""))


def _seg(s: dict) -> str:
    return f"Ep {s['episode']} · {s['start_ts']} → {s['end_ts']}"


# what each part of the score means, in plain words (keys = rank.score_promos components)
PARTS = [
    ("hook", "Hook", "AI rating of the first 3 seconds"),
    ("cliffhanger", "Cliffhanger", "AI rating of the ending"),
    ("standalone", "Makes sense alone", "AI rating: clear to a new viewer"),
    ("archetype_priority", "Genre fit", "how high this promo type sits in the genre playbook"),
    ("rule_score", "Drama intensity", "slaps, threats, reveals in the clip vs. the most intense clip in the show"),
    ("early_episode_bonus", "Early in the show", "earlier episodes = fewer spoilers"),
]
DEFAULT_WEIGHTS = {"hook": 0.30, "cliffhanger": 0.25, "standalone": 0.20, "archetype_priority": 0.15,
                   "rule_score": 0.10, "early_episode_bonus": 0.05}


def _weights(r: dict) -> dict:
    """Score weights of the show's genre (stored in promos.json; older runs: read genres.yaml)."""
    if r.get("weights"):
        return r["weights"]
    try:
        import yaml
        g = yaml.safe_load((Path(__file__).resolve().parent.parent / "genres.yaml").read_text(encoding="utf-8"))
        return g["genres"][r["profile"]["primary_genre"]].get("weights", g["default_weights"])
    except Exception:
        return DEFAULT_WEIGHTS


def _bar(label: str, frac: float, weight: float) -> str:
    pct = round(100 * max(0.0, min(1.0, frac)))
    return (f"<span>{label}</span>"
            f"<div class='bar'><i style='width:{pct}%'></i></div><span>{pct}%</span>")


def _final(p: dict) -> float:
    return float(p["scores"].get("final", 0))


def _card(p: dict, wts: dict, n_shortlist: int) -> str:
    s = p["scores"]
    comp = s.get("components") or {}
    segs = "".join(f"<span class='seg'>{_e(_seg(x))}</span>" for x in p["segments"])
    tags = [f"<span class='tag'>{p['duration']:.0f} s</span>"]
    if p["type"] == "stitched":
        tags.append("<span class='tag stitch'>joins episodes</span>")
    if p.get("archetype_name") and p["archetype_name"] != "other":
        tags.append(f"<span class='tag'>{_e(p['archetype_name'])}</span>")
    if p.get("source") == "rules":
        tags.append("<span class='tag'>rule-based</span>")
    why_first = (f"<div class='why'><b>Why post it #{p['rank']}:</b> {_e(p['why_post_first'])}</div>"
                 if p.get("why_post_first") else "")
    if p.get("editor_rank"):
        pick = (f"<div class='pick'>✔ AI editor's pick #{p['editor_rank']} after comparing the "
                f"{n_shortlist} highest-scoring clips side by side</div>")
    else:
        pick = "<div class='pick'>Placed by score, with a variety rule (no two similar promos back to back)</div>"
    total_w = sum(wts.get(k, 0) for k, _, _ in PARTS) or 1
    bars = "".join(_bar(f"<span title='{_e(tip)}'>{lab}</span>", comp.get(k, 0), wts.get(k, 0) / total_w)
                   for k, lab, tip in PARTS if wts.get(k))
    n_warn = len([w for w in p.get("warnings", []) if "snapped" not in w])
    minus = f"<div class='warn'>−{3 * n_warn} points for editing warnings</div>" if n_warn else ""
    warns = [w for w in p.get("warnings", []) if "snapped" not in w]
    warn = f"<div class='warn'>⚠ {_e('; '.join(warns))}</div>" if warns else ""
    script = (f"<details><summary>Read the promo script</summary><pre>{_e(chr(10).join(p['script']))}</pre></details>"
              if p.get("script") else "")
    return f"""
<article class="card{' first' if p['rank'] == 1 else ''}">
  <div class="top"><div class="rank">{p['rank']}</div>
    <div class="head"><div class="title">{_e(p['title'])}</div><div class="tags">{''.join(tags)}</div></div>
    <div class="score"><b>{_final(p):.0f}</b><span>/ 100</span></div></div>
  {pick}
  <div class="segs">{segs}</div>
  <div class="row"><span class="k">Hook · first 3 seconds</span>{_e(p['hook'])}</div>
  <div class="row"><span class="k">Ends on (cliffhanger)</span>{_e(p['cliffhanger'])}</div>
  <div class="row"><span class="k">Why it works</span>{_e(p['why_it_works'])}</div>
  {why_first}
  <div class="bars">{bars}</div>
  {minus}{warn}{script}
</article>"""


def write_html(r: dict, out: Path, top_n: int = 10) -> Path:
    promos = r["promos"]
    prof = r["profile"]
    st = r["stats"]
    top, rest = promos[:top_n], promos[top_n:]
    eps_covered = len({s["episode"] for p in promos for s in p["segments"]})
    stitched = sum(p["type"] == "stitched" for p in promos)
    genre = prof["primary_genre"].replace("_", " ")
    if prof.get("secondary_genre"):
        genre += " + " + prof["secondary_genre"].replace("_", " ")
    note = ""
    if st.get("episodes_rules_fallback"):
        note = (f"<div class='note'>⚠ The AI was unavailable for episodes {', '.join(map(str, st['episodes_rules_fallback']))}; "
                "those promos come from the simple rules only. Run again later to finish them.</div>")
    if r.get("editor_notes"):
        note += f"<div class='note'><b>Posting strategy:</b> {_e(r['editor_notes'])}</div>"
    wts = _weights(r)
    total_w = sum(wts.get(k, 0) for k, _, _ in PARTS) or 1
    n_short = min(20, len(promos))
    has_editor = any(p.get("editor_rank") for p in promos)
    wt_chips = "".join(f"<span class='tag' title='{_e(tip)}'>{lab} {100 * wts.get(k, 0) / total_w:.0f}%</span>"
                       for k, lab, tip in PARTS if wts.get(k))
    step2 = (f"<li><b>Head-to-head:</b> the AI editor compares the {n_short} highest-scoring clips side by side and "
             "chooses the posting order of the top 10 (scores alone are too close to separate the best clips).</li>"
             if has_editor else "")
    rater = "the AI" if r.get("mode") == "llm" else "the simple rule scorer (no AI in this run)"
    how = f"""<div class="how"><h3>How the order is decided</h3><ol>
<li><b>Score out of 100:</b> {rater} rates each clip's hook, cliffhanger and whether it makes sense alone; the tool adds
genre fit, drama intensity from the script, and a small bonus for early episodes. Editing warnings cost 3 points each.</li>
{step2}<li><b>Everything else</b> follows the score, with a variety rule so similar promos or the same episode don't run back to back.</li>
</ol><div class="wts">{wt_chips}</div></div>"""
    stitch_tag = ' <span class="tag stitch">joins episodes</span>'
    rows = "".join(
        f"<tr><td>{p['rank']}</td><td><b>{_e(p['title'])}</b>{stitch_tag if p['type'] == 'stitched' else ''}"
        f"<br><span class='sub'>{_e(p['hook'])}</span></td>"
        f"<td class='mono'>{'<br>'.join(_e(_seg(x)) for x in p['segments'])}</td><td>{p['duration']:.0f} s</td>"
        f"<td class='num'>{_final(p):.0f}/100</td></tr>" for p in rest)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Promo picks — {_e(r['show'])}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header>
  <div class="eyebrow">Promo picks · {_e(genre)}</div>
  <h1>{_e(r['show'])}</h1>
  <p class="premise">{_e(prof.get('premise'))}</p>
  <div class="stats">
    <div class="stat"><b>{r['episodes']}</b><span>episodes read</span></div>
    <div class="stat"><b>{len(promos)}</b><span>promos found</span></div>
    <div class="stat"><b>{stitched}</b><span>join two episodes</span></div>
    <div class="stat"><b>{eps_covered}/{r['episodes']}</b><span>episodes with a promo</span></div>
    <div class="stat"><b>{len(r.get('rejected', []))}</b><span>weak options dropped</span></div>
  </div>
</header>
{note}
{how}
<h2>Top {len(top)} — post these first</h2>
<p class="sub">In posting order. Each promo is 20–60 seconds: it opens on a hook and cuts on a cliffhanger. Times are from the episode scripts.</p>
<section class="grid">{''.join(_card(p, wts, n_short) for p in top)}</section>
{f'''<h2>All other promos</h2><p class="sub">Score out of 100, worked out as described above.</p>
<div class="tablewrap"><table><thead><tr><th>#</th><th>Promo &amp; hook</th><th>Where</th><th>Length</th><th>Score</th></tr></thead>
<tbody>{rows}</tbody></table></div>''' if rest else ''}
<footer>Generated {_e(r['generated_at'])} · {_e(r['mode'])} · {_e(', '.join(r.get('models_used') or []) or 'no AI')}</footer>
</div></body></html>"""
    path = out / "promos.html"
    path.write_text(page, encoding="utf-8")
    return path
