"""Orchestrates steps 1-7. Used by both run.py (CLI) and app.py (Streamlit)."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Callable

import yaml

from .candidates import Candidate, Rules, all_candidates
from .compress import beat_sheet, est_tokens, promo_script
from .judge import editor_review, judge_batches, rubric_scores, stitch
from .llm import LLM
from .parser import Episode, parse_folder
from .profile import build_profile, speaker_map
from .rank import archetype_lookup, posting_order, score_promos, strength
from .validate import beats_to_segment, dedupe, finalize_segments, hook_check

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path: Path | str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _rules_scores(c: Candidate, all_c: list[Candidate]) -> tuple[float, float]:
    """No-LLM mode: rule hook/cliff scores on 0-100, compared with a typical window of the show (rank.strength)."""
    return (round(100 * strength(c.hook_score, [x.hook_score for x in all_c]), 1),
            round(100 * strength(c.cliff_score, [x.cliff_score for x in all_c]), 1))


def run(folder: str | Path, out_dir: str | Path | None = None, use_llm: bool = True,
        config_path: Path | str = ROOT / "config.yaml", genres_path: Path | str = ROOT / "genres.yaml",
        full_context: bool = False, log: Callable[[str], None] = print, config_override: dict | None = None) -> dict:
    t0 = time.time()
    cfg = load_yaml(config_path)
    if config_override:
        for sect, vals in config_override.items():
            cfg.setdefault(sect, {}).update(vals)
    gcfg = load_yaml(genres_path)
    playbooks = gcfg["genres"]
    pcfg = cfg["promo"]
    folder = Path(folder)
    show = folder.name
    out = Path(out_dir) if out_dir else ROOT / "outputs" / _slug(show)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "llm_raw").exists():  # raw outputs must belong to THIS run only
        import shutil
        shutil.rmtree(out / "llm_raw")

    # 1-2 parse + compress -------------------------------------------------
    episodes = parse_folder(folder)
    by_no = {e.number: e for e in episodes}
    raw_chars = sum((folder / e.file).stat().st_size for e in episodes)
    log(f"[1] parsed {len(episodes)} episodes, {sum(len(e.events) for e in episodes)} beats")

    llm = LLM(cfg["llm"], raw_dir=out / "llm_raw") if use_llm else None
    if llm:
        log(f"[llm] {llm.describe()}")

    # 3 series profile ------------------------------------------------------
    prefer = cfg["llm"].get("editor_model")
    try:
        profile = build_profile(episodes, playbooks, llm, prefer=prefer)
    except Exception as e:
        log(f"  series profile: no LLM answer ({str(e)[:80]}) -> keyword fallback")
        profile = build_profile(episodes, playbooks, None)
    smap = speaker_map(profile) if use_llm else {}
    log(f"[3] genre: {profile.primary_genre} / {profile.secondary_genre or '-'}  ({profile.genre_reason[:80]})")
    compact_chars = sum(len(beat_sheet(e, speaker_map=smap)) for e in episodes)

    # 4 rule candidates -----------------------------------------------------
    rules = Rules.from_playbooks(gcfg, profile.primary_genre, profile.secondary_genre)
    cands = all_candidates(episodes, rules, pcfg)
    flat = [c for v in cands.values() for c in v]
    log(f"[4] {len(flat)} rule-based candidate windows")

    arch_info = archetype_lookup(playbooks, profile.primary_genre, profile.secondary_genre)
    promos: list[dict] = []
    rejected: list[dict] = []

    # 5 judge -----------------------------------------------------------------
    judged = judge_batches(episodes, cands, profile, playbooks, smap, pcfg, llm, full_context) if llm else {}
    for c in flat:
        ep = by_no[c.episode]
        warns: list[str] = []
        if llm:
            j = judged.get(c.id)
            if j is None:
                warns.append("judge returned nothing for this candidate; using rule window")
            elif not j.keep:
                rejected.append({"candidate": c.to_dict(), "judge": j.model_dump()})
                continue
        else:
            j = None
        if j is not None:
            seg, w = beats_to_segment(ep, j.start_beat, j.end_beat)
            warns += w
            if seg is None:
                seg = {"episode": ep.number, "start": c.start, "end": c.end, "start_beat": c.start_beat, "end_beat": c.end_beat}
                warns.append("judge gave invalid beat ids; fell back to rule window")
            rubric, g = rubric_scores(j)
            hs, cs, ss = g["hook"], g["cliffhanger"], g["standalone"]
            title, hook, cliff, why, arch, issue = j.title, j.hook, j.cliffhanger, j.why_it_works, j.archetype, j.standalone_issue
        else:
            seg = {"episode": ep.number, "start": c.start, "end": c.end, "start_beat": c.start_beat, "end_beat": c.end_beat}
            hs, cs = _rules_scores(c, flat)
            ss = 50.0  # not assessed without the AI: neutral
            rubric = None
            arch = c.archetype or "other"
            title = f"E{ep.number} {arch_info.get(arch, {}).get('name', 'conflict peak')}"
            hook, cliff = c.hook_text, c.cliff_text
            why = "Rule-based: " + ", ".join(c.reasons)
            issue = "not assessed (no LLM)"
        segs, w = finalize_segments([seg], by_no, pcfg)
        warns += w
        warns += hook_check(segs[0], ep, pcfg["hook_window"])
        promos.append({
            "id": c.id, "type": "single", "source": "llm" if j else "rules", "title": title,
            "segments": segs, "duration": round(sum(s["duration"] for s in segs), 2),
            "hook": hook, "cliffhanger": cliff, "why_it_works": why,
            "archetype": arch, "archetype_name": arch_info.get(arch, {}).get("name", "other"),
            "standalone_issue": issue,
            "scores": {"hook": hs, "cliffhanger": cs, "standalone": ss, "rule": c.rule_score,
                       "archetype_priority": arch_info.get(arch, {}).get("priority", 0.4),
                       **({"rubric": rubric} if rubric else {})},
            "rule_window": {"start": c.start, "end": c.end, "hook_text": c.hook_text, "cliff_text": c.cliff_text},
            "warnings": warns,
        })

    weights = playbooks[profile.primary_genre].get("weights", gcfg["default_weights"])
    rule_pool = [c.rule_score for c in flat]
    score_promos(promos, weights, len(episodes), rule_pool)
    promos = dedupe(promos)
    # keep at most N per episode
    per_ep: dict[int, int] = {}
    capped = []
    for p in sorted(promos, key=lambda p: -p["scores"]["final"]):
        e = p["segments"][0]["episode"]
        if per_ep.get(e, 0) < pcfg.get("max_promos_per_episode", 2):
            capped.append(p)
            per_ep[e] = per_ep.get(e, 0) + 1
    promos = capped
    fallback_eps = sorted({p["segments"][0]["episode"] for p in promos if p["source"] == "rules"}) if llm else []
    log(f"[5-6] {len(promos)} single-episode promos kept, {len(rejected)} rejected by judge")
    if fallback_eps:
        log(f"  NOTE: no LLM answer for episodes {fallback_eps} -> their promos are rule-based (marked source=rules)")

    # 5b stitched promos ----------------------------------------------------
    if llm and pcfg.get("stitched_promos", 0) > 0:
        top = sorted(promos, key=lambda p: -p["scores"]["final"])[:14]
        try:
            st = stitch(episodes, top, profile, playbooks, smap, pcfg, llm, prefer=prefer)
        except Exception as e:  # stitching is optional; never lose the main run
            log(f"  stitching failed: {e}")
            st = []
        med_rule = statistics.median([p["scores"]["rule"] for p in promos]) if promos else 0
        for i, s in enumerate(st, 1):
            warns, raw_segs = [], []
            for sg in s.segments:
                if sg.episode not in by_no:
                    warns.append(f"unknown episode {sg.episode}")
                    continue
                seg, w = beats_to_segment(by_no[sg.episode], sg.start_beat, sg.end_beat)
                warns += w
                if seg:
                    raw_segs.append(seg)
            if len(raw_segs) < 2:
                rejected.append({"stitched": s.model_dump(), "reason": "fewer than 2 valid segments", "warnings": warns})
                continue
            segs, w = finalize_segments(raw_segs, by_no, pcfg)
            warns += w
            warns += hook_check(segs[0], by_no[segs[0]["episode"]], pcfg["hook_window"])
            promos.append({
                "id": f"S{i}", "type": "stitched", "source": "llm", "title": s.title, "segments": segs,
                "duration": round(sum(x["duration"] for x in segs), 2), "hook": s.hook, "cliffhanger": s.cliffhanger,
                "why_it_works": s.why_it_works, "archetype": s.archetype,
                "archetype_name": arch_info.get(s.archetype, {}).get("name", "other"),
                "standalone_issue": s.standalone_issue,
                "scores": {"hook": rubric_scores(s)[1]["hook"], "cliffhanger": rubric_scores(s)[1]["cliffhanger"],
                           "standalone": rubric_scores(s)[1]["standalone"], "rubric": rubric_scores(s)[0],
                           "rule": med_rule, "archetype_priority": arch_info.get(s.archetype, {}).get("priority", 0.4)},
                "warnings": warns,
            })
        score_promos([p for p in promos if p["type"] == "stitched"], weights, len(episodes), rule_pool)
        log(f"[5b] {sum(p['type'] == 'stitched' for p in promos)} stitched promos")

    usage = llm.usage if llm else None
    # readable promo script for every promo (what the viewer will see and hear, in order)
    for p in promos:
        lines, off = [], 0.0
        for sg in p["segments"]:
            if len(p["segments"]) > 1:
                lines.append(f"--- segment: E{sg['episode']:02d} {sg['start_ts']}-{sg['end_ts']} ---")
            lines += promo_script(by_no[sg["episode"]], sg["start"], sg["end"], smap, off)
            off += sg["end"] - sg["start"]
        p["script"] = lines

    # 7 rank ------------------------------------------------------------------
    review_notes = ""
    if llm and promos:
        shortlist = sorted(promos, key=lambda p: -p["scores"]["final"])[:20]
        try:
            rev = editor_review(shortlist, profile, playbooks, pcfg, llm, prefer=prefer)
            ids = {p["id"]: p for p in shortlist}
            picked = []
            for k, pk in enumerate(rev.order, 1):
                if pk.id in ids and ids[pk.id] not in picked:
                    ids[pk.id]["editor_rank"] = k
                    ids[pk.id]["why_post_first"] = pk.why_post_first
                    picked.append(ids[pk.id])
            review_notes = rev.notes
            rest = posting_order([p for p in promos if p not in picked])
            ordered = picked + rest
            for i, p in enumerate(ordered, 1):
                p["rank"] = i
            log(f"[7] editor review ordered the top {len(picked)}")
        except Exception as e:
            log(f"  editor review failed ({e}); using score-based order")
            ordered = posting_order(promos)
    else:
        ordered = posting_order(promos)

    result = {
        "show": show,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "llm" if llm else "rules-only",
        "model": llm.describe() if llm else None,
        "models_used": sorted({x["model"] for x in usage.log if x.get("model")}) if usage else [],
        "profile": profile.model_dump(),
        "episodes": len(episodes),
        "promos": ordered,
        "rejected": rejected,
        "editor_notes": review_notes,
        "weights": weights,
        "score_scale": 100,
        "stats": {
            "raw_tokens_est": raw_chars // 4,
            "beat_sheet_tokens_est": compact_chars // 4,
            "llm_calls": usage.calls if usage else 0,
            "llm_cached_calls": usage.cached if usage else 0,
            "llm_input_tokens": usage.input_tokens if usage else 0,
            "llm_output_tokens": usage.output_tokens if usage else 0,
            "full_run_input_tokens": (usage.input_tokens + usage.cached_input_tokens) if usage else 0,
            "full_run_output_tokens": (usage.output_tokens + usage.cached_output_tokens) if usage else 0,
            "llm_log": usage.log if usage else [],
            "seconds": round(time.time() - t0, 1),
            "episodes_rules_fallback": fallback_eps,
        },
    }
    (out / "promos.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    (out / "candidates_rules.json").write_text(json.dumps({k: [c.to_dict() for c in v] for k, v in cands.items()}, indent=2, ensure_ascii=False))
    from .report import write_reports
    write_reports(result, out, pcfg.get("top_n_report", 25))
    log(f"[7] wrote {out}/promos.md, promos.csv, promos.json  ({result['stats']['seconds']}s)")
    return result


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60] or "show"
