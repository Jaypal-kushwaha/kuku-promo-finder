"""Research knowledge pack -> compact 'editor rules' block for the judge prompt.

The pack (knowledge/promo_knowledge.json) can be long and fully sourced. Only the
actionable parts are sent to the LLM, capped at `knowledge_max_chars`, so the
model gets pre-decided storytelling assumptions (what is a hook, what is a
cliffhanger) instead of re-deriving them, and token use stays bounded.

    python -m promo_finder.knowledge knowledge/promo_knowledge.json    # validate + preview
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SECTIONS = [  # (key, heading, max items) in priority order: earlier sections survive the char cap
    ("llm_decision_rules", "DECISION RULES", 14),
    ("hook_rankings", "HOOK STRENGTH (strongest first)", 8),
    ("cliffhanger_findings", "CLIFFHANGERS", 6),
    ("retention_findings", "RETENTION", 5),
    ("microdrama_specific_insights", "MICRODRAMA", 5),
    ("weak_or_risky_principles", "AVOID", 6),
]


def _item_text(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):  # e.g. {"technique": ..., "why_it_underperforms": ...}
        head = x.get("technique") or x.get("principle") or x.get("rule") or x.get("hook") or ""
        why = x.get("why_it_underperforms") or x.get("why_it_works") or x.get("when") or x.get("best_application") or ""
        return f"{head}: {why}".strip(": ") if head else json.dumps(x, ensure_ascii=False)
    return str(x)


def compact(pack: dict, max_chars: int = 2400) -> str:
    out, used = [], 0
    for key, head, n in SECTIONS:
        items = [_item_text(i) for i in (pack.get(key) or [])[:n] if i]
        if not items:
            continue
        block = head + ":\n" + "\n".join(f"- {t}" for t in items)
        if used + len(block) > max_chars:
            # add as many lines of this section as still fit
            lines = [head + ":"]
            for t in items:
                ln = f"- {t}"
                if used + sum(len(x) + 1 for x in lines) + len(ln) > max_chars:
                    break
                lines.append(ln)
            if len(lines) > 1:
                out.append("\n".join(lines))
            break
        out.append(block)
        used += len(block) + 1
    return "\n".join(out)


def load_rules(path: str | Path | None, max_chars: int = 2400) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    if not p.exists():
        return ""
    try:
        pack = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  [knowledge] {p} is not valid JSON ({e}); continuing without it")
        return ""
    return compact(pack, max_chars)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "knowledge/promo_knowledge.json"
    pack = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k, _, _ in SECTIONS if not pack.get(k)]
    txt = compact(pack)
    print(txt)
    print(f"\n--- {len(txt)} chars ≈ {len(txt) // 4} tokens per judge call · sections missing: {missing or 'none'} · "
          f"sources: {len(pack.get('sources') or [])}")
