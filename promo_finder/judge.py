"""Step 5 — LLM judge (+ cross-episode stitching).

The LLM sees compact beat sheets around the rule-based candidates and answers
with BEAT IDS, never timestamps. It refines start/end, writes the hook,
cliffhanger and why-it-works line, and scores hook / cliffhanger / standalone.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .candidates import Candidate
from .compress import beat_sheet
from .knowledge import load_rules
from .parser import Episode
from .profile import SeriesProfile


class Judged(BaseModel):
    candidate_id: str
    keep: bool = Field(description="false if this is not a usable promo even after adjusting the cut")
    title: str = Field(description="3-6 word working title for the promo")
    start_beat: int = Field(description="beat id (the number after 'b') where the promo starts; must be a beat shown")
    end_beat: int = Field(description="beat id of the LAST beat included; must be a beat shown")
    hook: str = Field(description="What stops the scroll in the first 3 seconds (quote the line/action)")
    cliffhanger: str = Field(description="The unresolved moment the promo cuts on")
    why_it_works: str = Field(description="One line")
    archetype: str = Field(description="playbook archetype id, or 'other'")
    hook_score: int = Field(ge=1, le=5)
    cliffhanger_score: int = Field(ge=1, le=5)
    standalone_score: int = Field(ge=1, le=5, description="5 = a stranger fully gets it; 1 = needs earlier episodes")
    standalone_issue: str = Field(default="", description="What a new viewer would not understand, or ''")


class JudgeBatch(BaseModel):
    results: list[Judged]


class Segment(BaseModel):
    episode: int
    start_beat: int
    end_beat: int


class Stitched(BaseModel):
    title: str
    segments: list[Segment] = Field(description="2-3 segments in play order; total 20-60 s")
    hook: str
    cliffhanger: str
    why_it_works: str
    archetype: str
    hook_score: int = Field(ge=1, le=5)
    cliffhanger_score: int = Field(ge=1, le=5)
    standalone_score: int = Field(ge=1, le=5)
    standalone_issue: str = ""


class StitchBatch(BaseModel):
    promos: list[Stitched]


def system_prompt(profile: SeriesProfile, playbooks: dict, cfg: dict) -> str:
    pb_keys = [k for k in (profile.primary_genre, profile.secondary_genre) if k]
    arch = []
    for k in pb_keys:
        for a in playbooks[k]["archetypes"]:
            arch.append(f"- {a['id']} (priority {a['priority']}): {a['name']}. {a['look_for']}")
    chars = "; ".join(f"{c.name} = {c.role}" for c in profile.characters[:14])
    rules = load_rules(cfg.get("knowledge_pack"), cfg.get("knowledge_max_chars", 2400))
    rules = (f"\nEDITOR KNOWLEDGE (pre-agreed assumptions from research; apply them, do not re-derive):\n{rules}\n"
             if rules else "")
    return f"""You are a senior promo editor for vertical microdramas (ReelShort / DramaBox style ads on TikTok, Reels, Shorts).
A promo is a {cfg['min_len']}-{cfg['max_len']} s clip cut from the show that pulls NEW viewers in. A good promo:
1. HOOK: something in the first 3 seconds stops a scrolling viewer (slap, reveal, shocking line). No slow setup.
2. CLIFFHANGER: it cuts at an unresolved moment (before the answer / the blow / the reveal lands).
3. STANDALONE: makes sense to someone who has never seen the show.

SHOW: {profile.title_guess}
PREMISE: {profile.premise}
CHARACTERS: {chars}
GENRE PLAYBOOK (archetypes in posting priority order):
{chr(10).join(arch)}
{rules}
BEAT SHEET FORMAT: 'b<id> <m:ss.s> SPEAKER(emotion): line' | ACT = action | SFX = sound | CAM = key visual.
Rules:
- Refer to cut points ONLY by beat ids that appear in the sheet. Never invent ids or timestamps.
- Use the beat timestamps to keep the clip between {cfg['min_len']} and {cfg['max_len']} seconds (end time ≈ next beat's time).
- Prefer to START on the most arresting line/action and END on the open question, threat or interrupted moment.
- Be a harsh critic: scores of 5 are rare; set keep=false for clips that are mostly quiet setup.
"""


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    spans = sorted(spans)
    out: list[list[float]] = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def episode_block(ep: Episode, cands: list[Candidate], smap: dict, pad: float, full: bool) -> str:
    if full:
        sheet = beat_sheet(ep, speaker_map=smap)
    else:
        spans = _merge([(max(0, c.start - pad), min(ep.duration, c.end + pad)) for c in cands])
        sheet = "\n...\n".join(beat_sheet(ep, a, b, speaker_map=smap) for a, b in spans)
    clist = "\n".join(
        f"- {c.id}: rule window b{c.start_beat}..b{c.end_beat} ({c.start:.1f}s-{c.end:.1f}s, {c.duration:.0f}s), "
        f"rule guess archetype={c.archetype or 'none'}" for c in cands)
    return (f"### EPISODE {ep.number} (length {ep.duration:.0f}s)\nLOGLINE: {ep.logline}\n"
            f"CANDIDATES:\n{clist}\nBEATS:\n{sheet}\n")


def judge_batches(episodes: list[Episode], cands: dict[int, list[Candidate]], profile: SeriesProfile,
                  playbooks: dict, smap: dict, cfg: dict, llm, full_context: bool = False,
                  _done: dict | None = None) -> dict[str, Judged]:
    sysmsg = system_prompt(profile, playbooks, cfg)
    eps = [e for e in episodes if cands.get(e.number)]
    size = max(1, cfg.get("episodes_per_call", 5))
    out: dict[str, Judged] = dict(_done or {})
    for i in range(0, len(eps), size):
        batch = eps[i:i + size]
        blocks = "\n".join(episode_block(e, cands[e.number], smap, cfg.get("context_pad", 8), full_context) for e in batch)
        ids = [c.id for e in batch for c in cands[e.number]]
        prompt = ((calibration_block(out) if cfg.get("calibration", True) else "") + f"{blocks}\nJudge EVERY candidate ({', '.join(ids)}). You may move start/end "
                  "to any beat shown for that episode to get a stronger hook or a sharper cliffhanger.")
        tag = f"02_judge_E{batch[0].number:02d}-E{batch[-1].number:02d}"
        print(f"  judging episodes {batch[0].number}-{batch[-1].number} ({len(ids)} candidates)")
        try:
            res = llm.call(sysmsg, prompt, JudgeBatch, tag=tag)
        except Exception as e:
            if len(batch) > 1 and not getattr(llm, "offline", False):
                # too big for a provider's per-minute limit, or bad luck: retry as two smaller requests
                print(f"  [judge] batch failed ({str(e)[:80]}); splitting it")
                half = len(batch) // 2
                for part in (batch[:half], batch[half:]):
                    sub = {e_.number: cands[e_.number] for e_ in part}
                    out.update(judge_batches(part, sub, profile, playbooks, smap, dict(cfg, episodes_per_call=len(part)),
                                             llm, full_context, _done=out))
                continue
            print(f"  [judge] episodes {batch[0].number}-{batch[-1].number}: no LLM answer ({str(e)[:80]}) -> rule-based result")
            continue
        for j in res.results:
            if j.candidate_id in ids:
                out[j.candidate_id] = j
    return out


def calibration_block(done: dict[str, Judged], k: int = 4) -> str:
    """Carry results forward: show the next batch (possibly a different model) a few already-judged promos -
    the best and the weakest kept - so every provider scores on the same scale."""
    kept = [j for j in done.values() if j.keep]
    if not kept:
        return ""
    kept.sort(key=lambda j: -(j.hook_score + j.cliffhanger_score + j.standalone_score))
    picks = kept[: k - 1] + ([kept[-1]] if len(kept) >= k else [])
    rows = "\n".join(f"- {j.candidate_id} \"{j.title}\": hook {j.hook_score}, cliff {j.cliffhanger_score}, standalone "
                     f"{j.standalone_score} - {j.why_it_works}" for j in picks)
    return ("CALIBRATION - promos already scored in earlier episodes of this show. Keep your 1-5 scale consistent "
            f"with these (a new clip gets a 5 only if it is at least as strong as the best here):\n{rows}\n\n")


def stitch(episodes: list[Episode], top: list[dict], profile: SeriesProfile, playbooks: dict,
           smap: dict, cfg: dict, llm, prefer: str | None = None) -> list[Stitched]:
    n = cfg.get("stitched_promos", 0)
    if n <= 0 or not top:
        return []
    by_no = {e.number: e for e in episodes}
    blocks = []
    for p in top:
        seg = p["segments"][0]
        ep = by_no[seg["episode"]]
        blocks.append(f"### {p['id']} | E{ep.number} | {p['title']} | archetype={p['archetype']}\n"
                      + beat_sheet(ep, seg["start"], seg["end"] - 0.01, speaker_map=smap))
    prompt = ("Below are the strongest single-episode promo moments. Build up to "
              f"{n} STITCHED promos, each joining 2-3 segments (from different moments, usually different episodes) "
              "into one 20-60 s promo that tells a mini-story: e.g. humiliation -> reversal tease, or crime -> "
              "framing -> threat. Each segment is a contiguous beat range from ONE block below (use its episode "
              "number and beat ids exactly as shown). Keep each segment short (5-25 s). Open on the strongest hook, "
              "end on the strongest unresolved moment. Only propose stitches that are clearly better than the "
              "single clips.\n\n" + "\n\n".join(blocks))
    res = llm.call(system_prompt(profile, playbooks, cfg), prompt, StitchBatch, tag="03_stitch", prefer=prefer)
    return res.promos[:n]


class PostPick(BaseModel):
    id: str
    why_post_first: str = Field(description="One line: why this slot in the posting order")


class EditorReview(BaseModel):
    order: list[PostPick] = Field(description="Promo ids in the order to post them, best first")
    notes: str = Field(default="", description="One or two lines on the overall strategy")


def editor_review(top: list[dict], profile: SeriesProfile, playbooks: dict, cfg: dict, llm, n: int = 10,
                  prefer: str | None = None) -> EditorReview:
    """Force-rank the shortlist. Per-clip 1-5 scores saturate (many 5/5/5); a head-to-head
    comparison discriminates better and answers 'which would you post first, and why?'."""
    lines = []
    for p in top:
        segs = " + ".join(f"E{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in p["segments"])
        lines.append(f"- {p['id']} [{p['type']}, {p['duration']:.0f}s, {segs}] \"{p['title']}\" | archetype: "
                     f"{p['archetype']} | hook: {p['hook']} | cliff: {p['cliffhanger']} | new-viewer gap: "
                     f"{p.get('standalone_issue') or 'none'} | judge scores H{p['scores']['hook']}/C{p['scores']['cliffhanger']}"
                     f"/S{p['scores']['standalone']}")
    prompt = (f"Shortlist of {len(top)} promos for this show:\n" + "\n".join(lines) +
              f"\n\nPick the {n} you would post FIRST, in order, for a launch week on TikTok/Reels. Compare them "
              "head-to-head: the first post must explain the show's premise to a stranger and hook hardest; "
              "later posts should add variety (different archetypes / story beats) and avoid spoiling the biggest "
              "twist too early unless it IS the selling point. Use only ids from the list.")
    return llm.call(system_prompt(profile, playbooks, cfg), prompt, EditorReview, tag="04_editor_review", prefer=prefer)
