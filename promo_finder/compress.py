"""Step 2 — turn parsed events into a compact 'beat sheet' for the LLM.

The raw screenplay is ~1/3 camera directions plus heavy formatting. Rules
here (no tokens spent) keep dialogue, action and sound fully, and keep a
camera line only when it carries story information (a kneel, chains, fire,
blood, "cut to black"...), stripped of shot-type jargon and truncated.
"""
from __future__ import annotations

import re

from .parser import Episode, Event, fmt_ts

# shot jargon to strip from the front of camera lines (word-bounded so "cut to black" survives)
_SHOT_WORDS = (
    r"extreme|tight|slow|fast|sweeping|dramatic|static|handheld|low|high|dutch|wide|medium|"
    r"close[- ]?ups?|close|over[- ]the[- ]shoulder|insert|establishing|tracking|aerial|overhead|profile|"
    r"symmetrical|push[- ]in|pushing|pull[- ]back|pull[- ]out|whip[- ]pan|crane|reverse|two[- ]shot|pov|"
    r"angle|shots?|framing|framed|lens|rack|focus|dolly|panning|pan|tilt|zoom|returning|"
    r"on|of|to|the|a|an|and|from|with|in|at|past|showing|centered"
)
RE_SHOT = re.compile(r"^(?:\b(?:" + _SHOT_WORDS + r")\b[\s,\-–]*)+", re.I)

# camera lines that carry story beats worth keeping for the LLM
CAMERA_KEEP = re.compile(
    r"\b(?:cut to black|smash cut|freeze|kneel\w*|chain\w*|blood\w*|fire|flames?|burn\w*|blade|sword|"
    r"knife|dagger|slap\w*|strikes?|struck|punch\w*|kiss\w*|embrac\w*|crest|scar\w*|crown|regalia|"
    r"explo\w*|bursts?|crash\w*|collaps\w*|faint\w*|seiz\w*|drag\w*|thrown?|mud|poison\w*|vial|"
    r"red-hot|noose|gallows|unmask\w*|recogni\w*|reveal\w*|signet|ledger|grimoire)\b",
    re.I,
)


def _short(text: str, max_words: int) -> str:
    words = text.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def short_ts(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:04.1f}"


def keep_event(ev: Event) -> bool:
    return ev.type != "camera" or bool(CAMERA_KEEP.search(ev.text))


def beat_line(ev: Event, speaker_map: dict[str, str] | None = None,
              camera_words: int = 12, action_words: int = 24) -> str | None:
    """One compact line per beat:  b17 1:15.0 GERALD(cold): "..."

    The 'b17' id is the event index. The LLM answers with beat ids, never with
    timestamps, so it cannot invent a time that is not in the script.
    """
    if not keep_event(ev):
        return None
    head = f"b{ev.idx} {short_ts(ev.start)}"
    if ev.type == "dialogue":
        who = (speaker_map or {}).get(ev.speaker, ev.speaker)
        emo = ev.emotion.split(",")[0].strip().lower() if ev.emotion else ""
        emo = f"({emo})" if emo else ""
        return f"{head} {who}{emo}: {ev.text}"
    if ev.type == "action":
        return f"{head} ACT: {_short(ev.text, action_words)}"
    if ev.type == "sfx":
        return f"{head} SFX: {_short(ev.text, 12)}"
    body = RE_SHOT.sub("", ev.text, count=1).strip() or ev.text
    return f"{head} CAM: {_short(body, camera_words)}"


def beat_sheet(ep: Episode, start: float = 0.0, end: float | None = None,
               speaker_map: dict[str, str] | None = None, **kw) -> str:
    end = ep.duration if end is None else end
    headings = {s.number: s.heading for s in ep.scenes}
    lines, cur_scene = [], None
    for ev in ep.events:
        if ev.start < start - 1e-6 or ev.start > end + 1e-6:
            continue
        if ev.scene != cur_scene and keep_event(ev):
            cur_scene = ev.scene
            if headings.get(ev.scene):
                lines.append(f"## SCENE {ev.scene}: {headings[ev.scene]}")
        ln = beat_line(ev, speaker_map, **kw)
        if ln:
            lines.append(ln)
    return "\n".join(lines)


def est_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token for English)."""
    return max(1, len(text) // 4)


def promo_script(ep: Episode, start: float, end: float, speaker_map: dict[str, str] | None = None,
                 offset: float = 0.0) -> list[str]:
    """Readable script of one promo segment: what the viewer hears/sees, with time inside the promo
    (+s, so the editor can see what lands in the first 3 s) and the source timestamp."""
    out = []
    for ev in ep.events:
        if not (start - 1e-6 <= ev.start < end) or not keep_event(ev):
            continue
        rel = offset + ev.start - start
        src = f"E{ep.number:02d} {short_ts(ev.start)}"
        if ev.type == "dialogue":
            who = (speaker_map or {}).get(ev.speaker, ev.speaker)
            emo = f" ({ev.emotion.split(',')[0].strip().lower()})" if ev.emotion else ""
            out.append(f"+{rel:04.1f}s [{src}] {who}{emo}: {ev.text}")
        elif ev.type == "action":
            out.append(f"+{rel:04.1f}s [{src}] ({ev.text})")
        elif ev.type == "sfx":
            out.append(f"+{rel:04.1f}s [{src}] SFX: {ev.text}")
        else:
            body = RE_SHOT.sub("", ev.text, count=1).strip() or ev.text
            out.append(f"+{rel:04.1f}s [{src}] VISUAL: {body}")
    return out
