"""Step 6 — deterministic checks on every promo (no LLM).

* beat ids exist in that episode and are in order
* segments snap to safe cut points (never mid-dialogue)
* total length 20-60 s (auto-extend / trim, with a warning)
* something visible/audible happens in the first 3 s (hook check)
* same-episode near-duplicates are removed
Every fix is recorded in `warnings`, so a human editor sees what changed.
"""
from __future__ import annotations

from .parser import Episode, fmt_ts, safe_cut_points


def _snap_down(t: float, cuts: list[float]) -> float:
    c = [x for x in cuts if x <= t + 1e-6]
    return c[-1] if c else cuts[0]


def _snap_up(t: float, cuts: list[float]) -> float:
    c = [x for x in cuts if x >= t - 1e-6]
    return c[0] if c else cuts[-1]


def beats_to_segment(ep: Episode, start_beat: int, end_beat: int) -> tuple[dict | None, list[str]]:
    warn = []
    n = len(ep.events)
    if not (0 <= start_beat < n and 0 <= end_beat < n):
        return None, [f"E{ep.number}: beat id out of range (b{start_beat}..b{end_beat}, episode has b0..b{n-1})"]
    if end_beat < start_beat:
        start_beat, end_beat = end_beat, start_beat
        warn.append("start/end beats were reversed; swapped")
    start = ep.events[start_beat].start
    # end = latest end among beats that START inside the range (camera lines overlap dialogue)
    end = max(e.end for e in ep.events if ep.events[start_beat].start <= e.start <= ep.events[end_beat].start)
    end = max(end, ep.events[end_beat].end)
    return {"episode": ep.number, "start": start, "end": end, "start_beat": start_beat, "end_beat": end_beat}, warn


def finalize_segments(segs: list[dict], by_no: dict[int, Episode], cfg: dict) -> tuple[list[dict], list[str]]:
    warn: list[str] = []
    out = []
    for s in segs:
        ep = by_no[s["episode"]]
        cuts = safe_cut_points(ep)
        a, b = _snap_down(s["start"], cuts), _snap_up(s["end"], cuts)
        if abs(a - s["start"]) > 0.05 or abs(b - s["end"]) > 0.05:
            warn.append(f"E{ep.number}: snapped to clean cut {fmt_ts(s['start'])}-{fmt_ts(s['end'])} -> {fmt_ts(a)}-{fmt_ts(b)}")
        out.append({**s, "start": a, "end": b})

    total = sum(s["end"] - s["start"] for s in out)
    lo, hi = cfg["min_len"], cfg["max_len"]
    if total < lo:  # extend the LAST segment forward to the next clean cuts
        last = out[-1]
        ep = by_no[last["episode"]]
        cuts = safe_cut_points(ep)
        need = lo - total
        new_end = _snap_up(last["end"] + need, cuts)
        if new_end - last["end"] + total >= lo - 0.5:
            warn.append(f"too short ({total:.1f}s): extended end to {fmt_ts(new_end)} — cliffhanger may have moved")
            last["end"] = new_end
        else:  # cannot extend past the episode end: extend the start backwards
            new_start = _snap_down(out[0]["start"] - need, safe_cut_points(by_no[out[0]["episode"]]))
            warn.append(f"too short ({total:.1f}s): moved start back to {fmt_ts(new_start)} — hook may be weaker")
            out[0]["start"] = new_start
    elif total > hi:  # trim the last segment's end, keeping the opening hook intact
        last = out[-1]
        ep = by_no[last["episode"]]
        excess = total - hi
        new_end = _snap_down(last["end"] - excess, safe_cut_points(ep))
        if new_end > last["start"] + 3:
            warn.append(f"too long ({total:.1f}s): trimmed end to {fmt_ts(new_end)} — check the cliffhanger")
            last["end"] = new_end
        else:
            warn.append(f"too long ({total:.1f}s) and could not trim cleanly")

    for s in out:
        s["start_ts"], s["end_ts"] = fmt_ts(s["start"]), fmt_ts(s["end"])
        s["duration"] = round(s["end"] - s["start"], 2)
    return out, warn


def hook_check(seg: dict, ep: Episode, window: float) -> list[str]:
    warns = []
    first = [e for e in ep.events if seg["start"] - 1e-6 <= e.start < seg["start"] + window and e.type != "camera"]
    if not first:
        warns.append(f"no dialogue/action/sound in the first {window:.0f}s — opens on a visual only (weak hook risk)")
    first_line = next((e for e in ep.events if e.start >= seg["start"] - 1e-6 and e.type == "dialogue"), None)
    if first_line and first_line.start < seg["start"] + window and first_line.text.lstrip('"“ ').startswith(("...", "…")):
        warns.append(f"opens mid-sentence (\"{first_line.text[:40]}\") — consider starting on the previous line")
    return warns


def overlap(a: dict, b: dict) -> float:
    """Overlap fraction for single-segment promos in the same episode."""
    if len(a["segments"]) != 1 or len(b["segments"]) != 1:
        return 0.0
    x, y = a["segments"][0], b["segments"][0]
    if x["episode"] != y["episode"]:
        return 0.0
    inter = min(x["end"], y["end"]) - max(x["start"], y["start"])
    return max(0.0, inter) / max(1e-6, min(x["end"] - x["start"], y["end"] - y["start"]))


def dedupe(promos: list[dict], thresh: float = 0.5) -> list[dict]:
    promos = sorted(promos, key=lambda p: -p["scores"]["final"])
    kept: list[dict] = []
    for p in promos:
        dup = next((k for k in kept if overlap(p, k) > thresh), None)
        if dup:
            dup.setdefault("merged_duplicates", []).append(p["id"])
        else:
            kept.append(p)
    return kept
