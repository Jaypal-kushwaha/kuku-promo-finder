"""Step 1 — parse microdrama screenplays into a flat, timestamped event list.

Pure code, zero LLM tokens. Tolerant of small format drift between episodes
(e.g. Episode 6 uses upper-case 'SCENE START:' headers).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

TS = r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)"

RE_EP_NUM = re.compile(r"^EPISODE NUMBER:\s*(?:Episode\s*)?(\d+)", re.I | re.M)
RE_LOGLINE = re.compile(r"^EPISODE LOGLINE:\s*(.+)$", re.I | re.M)
RE_CONT = re.compile(r"^CONTINUITY NOTES:\s*(.+)$", re.I | re.M)
RE_SCENE = re.compile(r"^SCENE\s+(\d+)\s*$", re.I | re.M)
RE_HEADING = re.compile(r"^Scene heading:\s*(.+)$", re.I | re.M)
RE_SC_START = re.compile(r"^Scene start:\s*" + TS, re.I | re.M)
RE_SC_END = re.compile(r"^Scene end:\s*" + TS, re.I | re.M)
# **LABEL (Emotion, Tags):**  newline  Start: (00:01.00) | End: (00:04.80)  newline  text...
RE_BLOCK = re.compile(
    r"^\*\*(?P<label>[^*\n]+?):?\*\*:?\s*\n"
    r"\s*Start:\s*\(?" + TS.replace("(", "(?P<start>", 1) + r"\)?\s*\|\s*End:\s*\(?" + TS.replace("(", "(?P<end>", 1) + r"\)?\s*\n"
    r"(?P<text>.*?)(?=\n\s*\n|\n\*\*|\n---|\nSCENE\s+\d|\Z)",
    re.I | re.M | re.S,
)

NON_DIALOGUE = {"CAMERA": "camera", "ACTION": "action", "SOUND FX": "sfx", "SFX": "sfx", "SOUND": "sfx", "MUSIC": "sfx"}


def to_seconds(ts: str) -> float:
    parts = ts.split(":")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return round(secs, 2)


def fmt_ts(sec: float) -> str:
    m, s = divmod(max(sec, 0.0), 60)
    return f"{int(m):02d}:{s:05.2f}"


@dataclass
class Event:
    idx: int
    type: str            # camera | action | sfx | dialogue
    start: float
    end: float
    text: str
    speaker: str = ""    # dialogue only (raw label, e.g. "LADY JULIANA")
    emotion: str = ""    # dialogue only, e.g. "Cold, Commanding"
    scene: int = 0


@dataclass
class Scene:
    number: int
    heading: str
    start: float
    end: float


@dataclass
class Episode:
    number: int
    file: str
    logline: str
    continuity: str
    duration: float
    scenes: list[Scene] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _classify(label: str) -> tuple[str, str, str]:
    """Return (type, speaker, emotion) from a block label like 'MATRIARCH (Cold, Commanding)'."""
    label = label.strip().rstrip(":").strip()
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", label)
    name, emotion = (m.group(1).strip(), m.group(2).strip()) if m else (label, "")
    key = name.upper()
    if key in NON_DIALOGUE:
        return NON_DIALOGUE[key], "", ""
    return "dialogue", key, emotion


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_episode(path: str | Path) -> Episode:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")

    m = RE_EP_NUM.search(raw)
    if m:
        number = int(m.group(1))
    else:  # fall back to the first number in the filename
        fm = re.search(r"(\d+)", path.stem)
        number = int(fm.group(1)) if fm else 0

    logline = _clean(RE_LOGLINE.search(raw).group(1)) if RE_LOGLINE.search(raw) else ""
    continuity = _clean(RE_CONT.search(raw).group(1)) if RE_CONT.search(raw) else ""

    # scenes: split text at SCENE markers so each block knows its scene
    scene_marks = list(RE_SCENE.finditer(raw))
    scenes: list[Scene] = []
    spans: list[tuple[int, int, int]] = []  # (char_start, char_end, scene_no)
    for i, sm in enumerate(scene_marks):
        s_from = sm.start()
        s_to = scene_marks[i + 1].start() if i + 1 < len(scene_marks) else len(raw)
        chunk = raw[s_from:s_to]
        h = RE_HEADING.search(chunk)
        st = RE_SC_START.search(chunk)
        en = RE_SC_END.search(chunk)
        scenes.append(Scene(
            number=int(sm.group(1)),
            heading=_clean(h.group(1)) if h else "",
            start=to_seconds(st.group(1)) if st else 0.0,
            end=to_seconds(en.group(1)) if en else 0.0,
        ))
        spans.append((s_from, s_to, int(sm.group(1))))

    def scene_of(pos: int) -> int:
        for a, b, n in spans:
            if a <= pos < b:
                return n
        return 0

    events: list[Event] = []
    for bm in RE_BLOCK.finditer(raw):
        etype, speaker, emotion = _classify(bm.group("label"))
        text = _clean(bm.group("text"))
        if not text:
            continue
        events.append(Event(
            idx=0, type=etype,
            start=to_seconds(bm.group("start")), end=to_seconds(bm.group("end")),
            text=text, speaker=speaker, emotion=emotion, scene=scene_of(bm.start()),
        ))
    events.sort(key=lambda e: (e.start, e.end))
    for i, e in enumerate(events):
        e.idx = i

    duration = max([s.end for s in scenes] + [e.end for e in events] + [0.0])
    return Episode(number, path.name, logline, continuity, duration, scenes, events)


def parse_folder(folder: str | Path) -> list[Episode]:
    folder = Path(folder)
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".txt", ".md", ".fountain"} and p.is_file())
    if not files:
        raise FileNotFoundError(f"No screenplay .txt files found in {folder}")
    eps = [parse_episode(p) for p in files]
    eps.sort(key=lambda e: e.number)
    return eps


def safe_cut_points(ep: Episode) -> list[float]:
    """Timestamps where a clip may start/end without slicing through a line of dialogue."""
    dlg = [(e.start, e.end) for e in ep.events if e.type == "dialogue"]
    pts = {0.0, ep.duration}
    for e in ep.events:
        pts.add(e.start)
        pts.add(e.end)
    ok = [t for t in pts if not any(a < t < b for a, b in dlg) and 0 <= t <= ep.duration]
    return sorted(ok)
