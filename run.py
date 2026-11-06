#!/usr/bin/env python3
"""Find promos in a microdrama.

  python run.py "<folder of episode .txt files>"             # LLM pool from config.yaml
  python run.py "<folder>" --no-llm                          # rules-only baseline, 0 tokens
  python run.py "<folder>" --cache-only                      # 0 tokens: finish with saved AI answers + rules for the rest
  python run.py --list-models                                # which providers/models your keys can use (0 tokens)
  python run.py --ping                                       # 1 tiny request per provider: proves each key works
  python run.py "<folder>" --strategy failover               # stay on one provider until its quota ends
  python run.py "<folder>" --model gemini-3.5-flash-lite     # one specific model only
  python run.py "<folder>" --provider openai_compat --base-url https://api.groq.com/openai/v1 \
        --model llama-3.3-70b-versatile --key-env GROQ_API_KEY   # any OpenAI-compatible API (e.g. one Kuku provides)
"""
import argparse

from promo_finder.pipeline import ROOT, load_yaml, run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", help="folder with one screenplay .txt per episode")
    ap.add_argument("--out", help="output folder (default outputs/<show>)")
    ap.add_argument("--no-llm", action="store_true", help="rules only, no API calls")
    ap.add_argument("--list-models", action="store_true", help="show models available to each configured key")
    ap.add_argument("--ping", action="store_true", help="send one tiny request to each provider (~60 tokens each)")
    ap.add_argument("--full-context", action="store_true", help="send whole episode beat sheets to the judge (more tokens)")
    ap.add_argument("--strategy", choices=["round_robin", "failover"])
    ap.add_argument("--provider", default="gemini")
    ap.add_argument("--model", help="use only this model (ignores the pool)")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--key-env", help="env var holding the API key (default GEMINI_API_KEY / NONE for local)")
    ap.add_argument("--episodes-per-call", type=int)
    ap.add_argument("--no-stitch", action="store_true")
    ap.add_argument("--cache-only", action="store_true",
                    help="0 tokens: use only answers already saved from earlier runs; the rest falls back to rules")
    a = ap.parse_args()

    if a.list_models:
        from promo_finder.llm import list_models
        list_models(load_yaml(ROOT / "config.yaml")["llm"])
        return
    if a.ping:
        from promo_finder.llm import ping
        ping(load_yaml(ROOT / "config.yaml")["llm"])
        return
    if not a.folder:
        ap.error("folder is required")

    llm: dict = {}
    if a.cache_only:
        llm["cache_only"] = True
    if a.strategy:
        llm["strategy"] = a.strategy
    if a.model:  # single model replaces the pool
        llm["pool"] = [{"name": "cli", "provider": a.provider, "model": a.model, "base_url": a.base_url,
                        "api_key_env": a.key_env or ("GEMINI_API_KEY" if a.provider == "gemini" else "NONE")}]
        llm["editor_model"] = "cli"
    promo: dict = {}
    if a.no_stitch:
        promo["stitched_promos"] = 0
    if a.episodes_per_call:
        promo["episodes_per_call"] = a.episodes_per_call
    run(a.folder, a.out, use_llm=not a.no_llm, full_context=a.full_context, config_override={"llm": llm, "promo": promo})


if __name__ == "__main__":
    main()
