"""Step 3 — series profile: genre, premise, character aliases.

One LLM call over loglines only (~3k tokens for 50 episodes). The result
picks the genre playbook and gives the judge the context it needs to decide
whether a clip makes sense to someone who has never seen the show.
A keyword fallback works without any LLM.
"""
from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, Field

from .parser import Episode


class Character(BaseModel):
    name: str = Field(description="Canonical short name, e.g. 'Alexander'")
    aliases: list[str] = Field(default_factory=list, description="Speaker labels used for this person in the script, UPPER CASE exactly as given")
    role: str = Field(description="One phrase, e.g. 'heroine', 'secret duke husband', 'cruel stepsister'")


class SeriesProfile(BaseModel):
    title_guess: str
    premise: str = Field(description="Two sentences a stranger needs to follow any clip")
    primary_genre: str = Field(description="One key from the playbook list")
    secondary_genre: str = Field(default="", description="Optional second key from the playbook list, or ''")
    genre_reason: str
    characters: list[Character]
    themes: list[str] = Field(default_factory=list)


SYSTEM = ("You are a story analyst for a vertical microdrama studio. Be factual: only use what the "
          "loglines and speaker list say. Do not invent characters.")


def build_prompt(episodes: list[Episode], playbooks: dict) -> str:
    speakers = Counter(ev.speaker for ep in episodes for ev in ep.events if ev.type == "dialogue")
    genre_list = "\n".join(f"- {k}: {v['label']}" for k, v in playbooks.items())
    loglines = "\n".join(f"E{ep.number}: {ep.logline}" for ep in episodes)
    spk = ", ".join(f"{s}({n})" for s, n in speakers.most_common(60))
    return (f"PLAYBOOK GENRES (choose keys from this list):\n{genre_list}\n\n"
            f"EPISODE LOGLINES:\n{loglines}\n\n"
            f"SPEAKER LABELS (line counts):\n{spk}\n\n"
            "Task: identify the show's genre (primary + optional secondary), write a two-sentence premise, "
            "and map EVERY speaker label that refers to a main or recurring character to one canonical character "
            "(e.g. 'MYSTERIOUS BEARDED MAN' and 'ALEXANDER' may be the same person; use loglines to decide). "
            "Skip one-off extras.")


def fallback_profile(episodes: list[Episode], playbooks: dict) -> SeriesProfile:
    text = " ".join(ep.logline.lower() for ep in episodes)
    scores = {}
    for key, pb in playbooks.items():
        scores[key] = sum(len(re.findall(r"\b" + re.escape(w.lower()) + r"\b", text)) for w in pb.get("detect", []))
    ranked = sorted(scores, key=scores.get, reverse=True)
    primary = ranked[0] if scores[ranked[0]] > 0 else "generic"
    secondary = ranked[1] if len(ranked) > 1 and scores[ranked[1]] > 0 else ""
    speakers = Counter(ev.speaker for ep in episodes for ev in ep.events if ev.type == "dialogue")
    chars = [Character(name=s.title(), aliases=[s], role="") for s, _ in speakers.most_common(12)]
    return SeriesProfile(
        title_guess="", premise=episodes[0].logline if episodes else "",
        primary_genre=primary, secondary_genre=secondary,
        genre_reason=f"keyword match scores {dict(sorted(scores.items(), key=lambda x: -x[1])[:3])}",
        characters=chars, themes=[])


def build_profile(episodes: list[Episode], playbooks: dict, llm=None, prefer: str | None = None) -> SeriesProfile:
    if llm is None:
        return fallback_profile(episodes, playbooks)
    prof = llm.call(SYSTEM, build_prompt(episodes, playbooks), SeriesProfile, tag="01_series_profile", prefer=prefer)
    if prof.primary_genre not in playbooks:  # model drifted off the list
        prof.genre_reason += f" (model said '{prof.primary_genre}', not a playbook key -> fallback)"
        prof.primary_genre = fallback_profile(episodes, playbooks).primary_genre
    if prof.secondary_genre and prof.secondary_genre not in playbooks:
        prof.secondary_genre = ""
    return prof


def speaker_map(profile: SeriesProfile) -> dict[str, str]:
    """UPPER-CASE speaker label -> canonical name, used to shorten / unify the beat sheet."""
    out = {}
    for c in profile.characters:
        for a in c.aliases:
            out[a.upper().strip()] = c.name.upper()
    return out
