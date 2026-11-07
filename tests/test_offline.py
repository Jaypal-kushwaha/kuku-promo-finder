"""Full pipeline test with a FAKE LLM: checks every code path (profile, judge, stitch, editor review,
validation, ranking, reports) without spending a single API token.

    .venv/bin/python tests/test_offline.py "<show folder>"
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from promo_finder import llm as L  # noqa: E402
from promo_finder import judge as J  # noqa: E402
from promo_finder.pipeline import run  # noqa: E402
from promo_finder.profile import Character, SeriesProfile  # noqa: E402


class FakeLLM:
    def __init__(self, cfg, raw_dir=None):
        self.usage = L.Usage()
        self.prompts = []

    def describe(self):
        return "fake"

    def call(self, system, prompt, schema, tag="call", prefer=None):
        self.prompts.append((tag, len(system) + len(prompt)))
        self.usage.calls += 1
        self.usage.log.append({"tag": tag, "model": "fake", "in": (len(system) + len(prompt)) // 4, "out": 0, "sec": 0})
        if schema is SeriesProfile:
            return SeriesProfile(title_guess="t", premise="p", primary_genre="hidden_identity_romance",
                                 secondary_genre="revenge_betrayal", genre_reason="fake",
                                 characters=[Character(name="Juliana", aliases=["LADY JULIANA", "JULIANA"], role="heroine")])
        RUB = dict(h_grab=8, h_emotion=7, h_question=6, c_unresolved=9, c_stakes=7, c_pull=8, s_clear=6, s_arc=5, s_premise=7)
        if schema is J.JudgeBatch:
            import re
            res = []
            for cid, a, b in re.findall(r"- (E\d+-C\d+): rule window b(\d+)\.\.b(\d+)", prompt):
                res.append(J.Judged(candidate_id=cid, keep=int(cid[-1]) != 3, title=f"T {cid}", start_beat=int(a),
                                    end_beat=int(b), hook="h", cliffhanger="c", why_it_works="w", archetype="identity_reveal",
                                    **RUB))
            res.append(J.Judged(candidate_id="E99-C9", keep=True, title="bogus", start_beat=99999, end_beat=1, hook="",
                                cliffhanger="", why_it_works="", archetype="x", **RUB))  # hallucinated id must be ignored
            return J.JudgeBatch(results=res)
        if schema is J.StitchBatch:
            import re
            blocks = re.findall(r"### (\S+) \| E(\d+) .*?\n(b\d+).*?\n(?:.*\n)*?", prompt)
            eps = re.findall(r"\| E(\d+) \|", prompt)
            beats = re.findall(r"^b(\d+) ", prompt, re.M)
            segs = [J.Segment(episode=int(eps[0]), start_beat=int(beats[0]), end_beat=int(beats[3])),
                    J.Segment(episode=int(eps[1]), start_beat=999999, end_beat=999999)]  # 2nd invalid -> rejected
            ok = [J.Segment(episode=int(eps[0]), start_beat=int(beats[0]), end_beat=int(beats[2])),
                  J.Segment(episode=int(eps[0]), start_beat=int(beats[4]), end_beat=int(beats[8]))]
            mk = lambda s, t: J.Stitched(title=t, segments=s, hook="h", cliffhanger="c", why_it_works="w",
                                         archetype="identity_reveal", **RUB)
            return J.StitchBatch(promos=[mk(segs, "invalid"), mk(ok, "valid")])
        if schema is J.EditorReview:
            import re
            ids = re.findall(r"^- (\S+) \[", prompt, re.M)
            return J.EditorReview(order=[J.PostPick(id=i, why_post_first="because") for i in ids[:10]] +
                                  [J.PostPick(id="NOPE", why_post_first="hallucinated")], notes="fake notes")
        raise AssertionError(schema)


def main():
    show = Path(sys.argv[1] if len(sys.argv) > 1 else next(p for p in ROOT.iterdir() if p.is_dir() and any(p.glob("episode-*.txt"))))
    tmp = Path(tempfile.mkdtemp())
    small = tmp / "mini_show"
    small.mkdir()
    for f in sorted(show.glob("*.txt"))[:9]:
        shutil.copy(f, small / f.name)
    import promo_finder.pipeline as P
    P.LLM = FakeLLM
    r = run(small, tmp / "out", use_llm=True, log=lambda m: None)
    P_ = r["promos"]
    assert P_, "no promos"
    assert all(20 - 0.5 <= p["duration"] <= 60.5 for p in P_), [p["duration"] for p in P_]
    assert all(p["script"] for p in P_)
    assert [p["rank"] for p in P_] == list(range(1, len(P_) + 1))
    assert any(p["type"] == "stitched" for p in P_), "valid stitch missing"
    assert any(x.get("reason") == "fewer than 2 valid segments" for x in r["rejected"]), "invalid stitch not rejected"
    assert not any(p["id"] == "E99-C9" for p in P_), "hallucinated candidate leaked"
    assert P_[0].get("why_post_first"), "editor order not applied"
    llm_p = [p for p in P_ if p["source"] == "llm" and p["type"] == "single"]
    assert llm_p and all(p["scores"].get("rubric") for p in llm_p), "checklist missing"
    assert llm_p[0]["scores"]["hook"] == 70.0 and llm_p[0]["scores"]["cliffhanger"] == 80.0, llm_p[0]["scores"]
    assert all(0 <= p["scores"]["final"] <= 100 for p in P_)
    html = (tmp / "out" / "promos.html").read_text()
    assert "Cuts before payoff" in html and "/ 100" in html, "html checklist/score missing"
    for f in ("promos.md", "promos.csv", "promos.json", "candidates_rules.json", "promos.html"):
        assert (tmp / "out" / f).exists(), f
    print(f"OK offline test: {len(P_)} promos, {len(r['rejected'])} rejected, "
          f"{r['stats']['llm_calls']} fake LLM calls, est. prompt tokens {sum(x['in'] for x in r['stats']['llm_log']):,}")


if __name__ == "__main__":
    main()
