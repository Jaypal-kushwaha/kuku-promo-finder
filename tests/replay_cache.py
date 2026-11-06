"""Rebuild a finished run from saved AI answers in .cache/llm (0 tokens).
Used once to recover the first complete 50-episode run (2026-11-07 02:23-02:27)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import promo_finder.pipeline as P  # noqa: E402
from promo_finder import judge as J, llm as L  # noqa: E402
from promo_finder.profile import SeriesProfile  # noqa: E402

FILES = {"profile": "8376e4179462189a3597410f", "stitch": "14ca2fd4b959c8f683bbe2c9", "editor": "8ba37897dd89b7172a5b577a",
         "judge": ["9e4f4022a4b78aaeccd5f1f1", "d606630e81fc930f66ec7d4f", "b73b676c168bfe4831ca35c0", "f2583f957ae9f044b0c9a7d0",
                   "a876d2d66b1329f344802936", "3641a91dc6ac523da8462e08", "829b67ff8348eeb4d6abb271", "e908d2219fab87727d60b75b",
                   "3abe4c64c068a46203444c89", "ca84c603e19a6833a4f5d7e6"]}


def load(h):
    d = json.loads((ROOT / ".cache/llm" / f"{h}.json").read_text())
    return d, L._extract_json(d["text"])


class Replay:
    def __init__(self, cfg, raw_dir=None):
        self.usage, self.raw_dir, self.offline = L.Usage(), raw_dir, False
        raw_dir.mkdir(parents=True, exist_ok=True)
        merged = []
        for n, h in enumerate(FILES["judge"], 1):
            d, t = load(h)
            merged += J.JudgeBatch.model_validate_json(t).results
            self._log("judge", d)
            self._raw(f"02_judge_batch{n:02d}_saved_response", d)
        self.judged = J.JudgeBatch(results=merged)

    def describe(self):
        return "replay of saved answers (gemini-3.5-flash for E01-E20 + profile, gemini-3.5-flash-lite for the rest)"

    def _log(self, tag, d):
        self.usage.cached += 1
        self.usage.cached_input_tokens += d.get("in", 0) or 0
        self.usage.cached_output_tokens += d.get("out", 0) or 0
        self.usage.log.append({"tag": tag, "model": d.get("model"), "in": d.get("in", 0), "out": d.get("out", 0), "cached": True})

    def _raw(self, name, d):
        (self.raw_dir / f"{name}.json").write_text(json.dumps(
            {"model": d.get("model"), "input_tokens": d.get("in"), "output_tokens": d.get("out"), "response": d["text"]},
            indent=2, ensure_ascii=False))

    def call(self, system, prompt, schema, tag="", prefer=None):
        (self.raw_dir / f"{tag}.json").write_text(json.dumps({"tag": tag, "replayed": True, "prompt": prompt}, indent=1))
        if schema is SeriesProfile:
            d, t = load(FILES["profile"]); self._log(tag, d); self._raw("01_series_profile_saved_response", d); return SeriesProfile.model_validate_json(t)
        if schema is J.JudgeBatch:
            return self.judged
        if schema is J.StitchBatch:
            d, t = load(FILES["stitch"]); self._log(tag, d); self._raw("03_stitch_saved_response", d); return J.StitchBatch.model_validate_json(t)
        if schema is J.EditorReview:
            d, t = load(FILES["editor"]); self._log(tag, d); self._raw("04_editor_review_saved_response", d); return J.EditorReview.model_validate_json(t)
        raise KeyError(schema)


if __name__ == "__main__":
    P.LLM = Replay
    r = P.run(ROOT / "I Married a Broken Soldier. He was a Duke", ROOT / "outputs/full_run_v1", use_llm=True,
              config_override={"promo": {"episodes_per_call": 5}}, log=lambda m: None if m.startswith("  judging") else print(m))
    print("rules-fallback episodes:", r["stats"]["episodes_rules_fallback"])
