"""Step 4 — rule-based candidate windows (0 tokens).

Every beat gets an 'intensity' score from the genre playbook lexicons. A
candidate promo is a 20-60 s window that
  * STARTS at a safe cut where the first 3 s are intense   (hook)
  * ENDS at a safe cut right after a tense beat / just before a payoff,
    or at the episode's own scripted cliffhanger              (cliffhanger)
Top-K non-overlapping windows per episode go to the LLM judge. The same
windows are the final answer in --no-llm mode, which gives a baseline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .parser import Episode, Event, safe_cut_points

CAT_WEIGHT = {"violence": 2.0, "reveal": 1.8, "threat": 1.5, "humiliation": 1.5, "betrayal": 1.5, "romance": 1.0}


def _compile(words: list[str]) -> re.Pattern | None:
    words = [w for w in words if w]
    if not words:
        return None
    parts = sorted({re.escape(w.lower()) for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![a-z])(?:" + "|".join(parts) + r")(?![a-z])", re.I)


@dataclass
class Rules:
    cats: dict[str, re.Pattern]
    emotion: re.Pattern | None
    cliff: re.Pattern | None
    weak: re.Pattern | None
    archetypes: list[dict]        # [{id, name, priority, rx}]

    @classmethod
    def from_playbooks(cls, genres_cfg: dict, primary: str, secondary: str = "") -> "Rules":
        common = genres_cfg["common"]
        cats = {k: _compile(v) for k, v in common["hook_words"].items()}
        arch = []
        for gkey, mult in ((primary, 1.0), (secondary, 0.8)):
            if not gkey or gkey not in genres_cfg["genres"]:
                continue
            for a in genres_cfg["genres"][gkey]["archetypes"]:
                arch.append({"id": a["id"], "name": a["name"], "priority": a["priority"] * mult,
                             "genre": gkey, "rx": _compile(a.get("triggers", []))})
        return cls(cats, _compile(common["emotion_words"]), _compile(common["cliffhanger_words"]),
                   _compile(common["weak_open_words"]), arch)


@dataclass
class BeatScore:
    intensity: float
    archetype: str = ""
    arch_priority: float = 0.0
    cliff: float = 0.0


def score_beat(ev: Event, r: Rules) -> BeatScore:
    text = ev.text.lower()
    s = 0.0
    for cat, rx in r.cats.items():
        if rx:
            n = len(rx.findall(text))
            s += CAT_WEIGHT.get(cat, 1.0) * min(n, 2)
    if ev.type == "dialogue":
        if ev.emotion and r.emotion and r.emotion.search(ev.emotion):
            s += 1.0
        s += 0.5 * ("!" in ev.text) + 0.3 * ("?" in ev.text)
        s += 0.3  # spoken lines read as hooks better than silent visuals
    elif ev.type == "sfx":
        s += 0.5
    elif ev.type == "camera":
        s *= 0.5
    if r.weak and r.weak.search(text):
        s -= 0.5
    best, bp = "", 0.0
    for a in r.archetypes:
        if a["rx"] and a["rx"].search(text) and a["priority"] > bp:
            best, bp = a["id"], a["priority"]
    s += 1.5 * bp
    cliff = 0.0
    if r.cliff:
        cliff += 1.5 * min(len(r.cliff.findall(text)), 2)
    if ev.type == "dialogue" and (ev.text.rstrip('"').endswith(("?", "...", "…", "!"))):
        cliff += 0.5
    return BeatScore(max(s, 0.0), best, bp, cliff)


@dataclass
class Candidate:
    id: str
    episode: int
    start: float
    end: float
    start_beat: int
    end_beat: int
    hook_score: float
    cliff_score: float
    rule_score: float
    archetype: str
    hook_text: str
    cliff_text: str
    reasons: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = self.duration
        return d


def _visible(ev: Event) -> bool:
    return ev.type != "camera"


def episode_candidates(ep: Episode, r: Rules, k: int, min_len: float, max_len: float,
                       hook_window: float = 3.0) -> list[Candidate]:
    evs = ep.events
    if not evs or ep.duration < min_len:
        return []
    scores = [score_beat(e, r) for e in evs]
    cuts = safe_cut_points(ep)
    cutset = set(cuts)

    def hook_at(t: float) -> float:
        return sum(scores[i].intensity * (1.0 if _visible(e) else 0.6)
                   for i, e in enumerate(evs) if t - 1e-6 <= e.start < t + hook_window)

    def cliff_at(t: float) -> float:
        tail = sum(scores[i].intensity * 0.5 + scores[i].cliff
                   for i, e in enumerate(evs) if t - 5.0 <= e.start < t and e.end <= t + 1e-6)
        nxt = sum(scores[i].intensity for i, e in enumerate(evs) if t <= e.start < t + 5.0)
        bonus = 3.0 if ep.duration - t <= 2.0 else 0.0  # the episode's own scripted cliffhanger
        return tail + 0.4 * nxt + bonus                   # cutting right BEFORE a payoff is a cliffhanger

    starts = sorted({e.start for e in evs if _visible(e) and e.start in cutset})
    ends = sorted({e.end for e in evs if e.end in cutset} | {ep.duration})
    hook_cache = {t: hook_at(t) for t in starts}
    cliff_cache = {t: cliff_at(t) for t in ends}
    inten_prefix = []
    acc = 0.0
    for sc in scores:
        acc += sc.intensity
        inten_prefix.append(acc)

    windows = []
    for s in starts:
        if hook_cache[s] <= 0.5:
            continue
        best = None
        for e in ends:
            if e - s < min_len:
                continue
            if e - s > max_len:
                break
            density = sum(scores[i].intensity for i, ev in enumerate(evs) if s <= ev.start < e) / max(e - s, 1)
            val = cliff_cache[e] + 2.0 * density
            if best is None or val > best[0]:
                best = (val, e, density)
        if best:
            total = hook_cache[s] * 1.0 + best[0]
            windows.append((total, s, best[1], best[2]))

    windows.sort(reverse=True)
    chosen: list[tuple] = []
    for w in windows:
        _, s, e, _ = w
        if all(min(e, ce) - max(s, cs) < 0.35 * min(e - s, ce - cs) for _, cs, ce, _ in chosen):
            chosen.append(w)
        if len(chosen) >= k:
            break

    out = []
    for n, (total, s, e, density) in enumerate(chosen, 1):
        inside = [i for i, ev in enumerate(evs) if s - 1e-6 <= ev.start < e and ev.end <= e + 1e-6]
        if not inside:
            continue
        hook_ev = [evs[i] for i in inside if evs[i].start < s + hook_window and _visible(evs[i])][:2]
        tail_ev = [evs[i] for i in inside if _visible(evs[i])][-2:]
        arch_scores: dict[str, float] = {}
        for i in inside:
            if scores[i].archetype:
                arch_scores[scores[i].archetype] = arch_scores.get(scores[i].archetype, 0) + scores[i].arch_priority
        arch = max(arch_scores, key=arch_scores.get) if arch_scores else ""
        reasons = [f"hook={hook_cache[s]:.1f}", f"cliff={cliff_cache[e]:.1f}", f"density={density:.2f}"]
        if ep.duration - e <= 2.0:
            reasons.append("ends on the episode's scripted cliffhanger")
        out.append(Candidate(
            id=f"E{ep.number:02d}-C{n}", episode=ep.number, start=s, end=e,
            start_beat=inside[0], end_beat=inside[-1],
            hook_score=round(hook_cache[s], 2), cliff_score=round(cliff_cache[e], 2), rule_score=round(total, 2),
            archetype=arch,
            hook_text=" / ".join(_fmt(ev) for ev in hook_ev),
            cliff_text=" / ".join(_fmt(ev) for ev in tail_ev),
            reasons=reasons))
    return out


def _fmt(ev: Event) -> str:
    if ev.type == "dialogue":
        return f'{ev.speaker}: {ev.text}'
    return ev.text if len(ev.text) < 140 else ev.text[:137] + "..."


def all_candidates(episodes: list[Episode], r: Rules, cfg: dict) -> dict[int, list[Candidate]]:
    return {ep.number: episode_candidates(ep, r, cfg["candidates_per_episode"], cfg["min_len"],
                                          cfg["max_len"], cfg["hook_window"]) for ep in episodes}
