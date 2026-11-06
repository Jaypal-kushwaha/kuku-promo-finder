"""Step 7 — score and order promos (pure code, weights from the genre playbook).

final = Σ weight × normalised component  (0-100), minus small penalties for
validation warnings. Posting order then adds diversity: we don't post three
'public betrayal' clips in a row, or two clips from the same episode back to back.
"""
from __future__ import annotations


def archetype_lookup(playbooks: dict, primary: str, secondary: str) -> dict[str, dict]:
    out = {}
    for key, mult in ((secondary, 0.8), (primary, 1.0)):  # primary wins on clashes
        if key and key in playbooks:
            for a in playbooks[key]["archetypes"]:
                out[a["id"]] = {"name": a["name"], "priority": round(a["priority"] * mult, 3), "genre": key}
    return out


def score_promos(promos: list[dict], weights: dict, n_episodes: int, max_rule: float) -> None:
    for p in promos:
        s = p["scores"]
        first_ep = min(seg["episode"] for seg in p["segments"])
        comp = {
            "hook": (s["hook"] - 1) / 4,
            "cliffhanger": (s["cliffhanger"] - 1) / 4,
            "standalone": (s["standalone"] - 1) / 4,
            "archetype_priority": s.get("archetype_priority", 0.4),
            "rule_score": min(1.0, s.get("rule", 0) / max_rule) if max_rule else 0,
            "early_episode_bonus": 1 - (first_ep - 1) / max(1, n_episodes - 1),
        }
        total = sum(weights.get(k, 0) * v for k, v in comp.items()) / max(1e-6, sum(weights.values()))
        penalty = 0.03 * len([w for w in p.get("warnings", []) if "snapped" not in w])
        s["components"] = {k: round(v, 3) for k, v in comp.items()}
        s["final"] = round(100 * max(0.0, total - penalty), 1)


def posting_order(promos: list[dict], arch_penalty: float = 6.0, ep_penalty: float = 4.0) -> list[dict]:
    pool = sorted(promos, key=lambda p: -p["scores"]["final"])
    order: list[dict] = []
    seen_arch: dict[str, int] = {}
    seen_ep: dict[int, int] = {}
    while pool:
        def adj(p):
            eps = {s["episode"] for s in p["segments"]}
            return (p["scores"]["final"] - arch_penalty * seen_arch.get(p["archetype"], 0)
                    - ep_penalty * sum(seen_ep.get(e, 0) for e in eps))
        best = max(pool, key=adj)
        pool.remove(best)
        best["post_order_score"] = round(adj(best), 1)
        order.append(best)
        seen_arch[best["archetype"]] = seen_arch.get(best["archetype"], 0) + 1
        for s in best["segments"]:
            seen_ep[s["episode"]] = seen_ep.get(s["episode"], 0) + 1
    for i, p in enumerate(order, 1):
        p["rank"] = i
    return order
