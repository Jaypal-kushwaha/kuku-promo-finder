# Microdrama Promo Finder

Reads a microdrama's episode screenplays and returns ranked 20–60 s promo clips. Each promo has
episode + start/end timestamps for every segment, the hook (first 3 s), the cliffhanger it cuts on,
one line on why it works, and a posting order.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# API keys go in .env (or any *.env file in this folder), one per line:
#   GEMINI_API_KEY=...   GROQ_API_KEY=...   MISTRAL_API_KEY=...   OPENROUTER_API_KEY=...
# A provider whose key is missing is skipped.

.venv/bin/python run.py --list-models                 # 0 tokens: which models each key can use
.venv/bin/python run.py --ping                        # ~60 tokens per provider: proves each key works
.venv/bin/python tests/test_offline.py                # 0 tokens: full pipeline with a fake LLM
.venv/bin/python run.py "path/to/show_folder" --no-llm   # 0 tokens: rules-only baseline (~2 s)
.venv/bin/python run.py "path/to/show_folder"            # full run, rotating the free providers in config.yaml
.venv/bin/streamlit run app.py                        # UI: upload episodes, review, approve, export
.venv/bin/python make_submission.py --doc Solution.pdf   # pack outputs into submission/ for Google Drive
```

The input is a folder with one screenplay `.txt` per episode, in the input-pack format (`**SPEAKER (Emotion):**` /
`Start: (mm:ss.xx) | End: (mm:ss.xx)` blocks). Outputs go to `outputs/<show>/`:

| file | what |
|---|---|
| `promos.md` | ranked report: posting order, segments, hook, cliffhanger, why, checks, and the **promo script** |
| `promos.csv` | the same as a sortable sheet for editors |
| `promos.json` | everything, including scores, warnings, token usage |
| `candidates_rules.json` | the rule-based windows before the LLM |
| `llm_raw/` | every prompt and the raw model response, unedited |

### Several free providers at once (`config.yaml → llm.pool`)

Episodes go out in batches of 4 (about 5k tokens, under the free per-minute limits).
- `strategy: round_robin` sends batch 1 to Gemini, batch 2 to Groq, batch 3 to Mistral, and so on.
- `strategy: failover` stays on one provider until its quota ends.

A provider that says "quota exhausted" is dropped for the rest of the run, and the next one takes over.

Each new batch also gets a few promos already scored by earlier batches (**calibration**), so different models grade
on the same scale. The series profile, stitching and the final posting order always use one model (`editor_model`).
A disk cache means a re-run, or a run interrupted by quota, never pays twice for the same request.

### Research knowledge pack (`knowledge/`)

`knowledge/promo_knowledge.json` holds pre-agreed rules about hooks, cliffhangers and standalone clarity. A compact
slice of it (capped at about 600 tokens) is added to the judge prompt, so the model applies agreed rules instead of
improvising its own. To refresh it, run `knowledge/research_prompt.md` in a web-search LLM, save the JSON there, and
check it with `.venv/bin/python -m promo_finder.knowledge`.

### Swap the model

```bash
run.py show/ --model gemini-3.5-flash-lite
run.py show/ --provider openai_compat --base-url https://api.groq.com/openai/v1 --model openai/gpt-oss-120b --key-env GROQ_API_KEY
run.py show/ --provider openai_compat --base-url http://localhost:11434/v1 --model qwen2.5:14b --key-env NONE   # Ollama
```
Any OpenAI-compatible endpoint works. The model is only ever called from `promo_finder/llm.py`.

## How it works

```
screenplays ─► [1] parse (code) ─► [2] compact beat sheet (code, ~3× fewer tokens)
           ─► [3] series profile: genre + characters (1 LLM call over loglines)
           ─► [4] rule candidates: genre-playbook lexicon scores every beat; best 20-60 s windows
                  that open hot and end on a tense beat / right before a payoff (code, 0 tokens)
           ─► [5] LLM judge: refine cut by BEAT ID, write hook / cliffhanger / why, score 1-5 (batched)
           ─► [5b] LLM stitching: 2-3 segment cross-episode promos from the best moments
           ─► [6] validate (code): beat ids exist, snap to clean cuts, 20-60 s, hook in 3 s, dedupe
           ─► [7] rank: playbook-weighted score + LLM head-to-head editor review for the top 10
```

- **The LLM never writes timestamps.** It answers with beat ids (`b68`) that code maps back to the script's own
  timestamps, so made-up times are impossible. Invalid ids fall back to the rule window and get flagged.
- **Genre playbooks (`genres.yaml`)** define, per genre, the promo archetypes in the order we'd post them, plus trigger
  words and ranking weights. A new show is mapped to a playbook automatically. These are hand-written assumptions,
  meant to be re-fit on Kuku's real promo performance data.
- **Free-tier friendly:** a 50-episode show takes about 16 small calls spread over the free providers,
  ~100k input / ~25k output tokens in total.
- **Human in the loop:** the Streamlit app shows each promo next to its beat sheet. The editor approves or rejects
  and exports the approved list.

## Evaluate

```bash
.venv/bin/python eval/quality.py outputs/<show>/promos.json \
    --gold eval/gold.yaml --ratings eval/ratings.yaml --compare outputs/rules_only/promos.json
```
This reports automatic-check failures, LLM score saturation, how much the LLM changed the rule windows, recall
against a human-marked gold set, human ratings of the top picks, and run-to-run / model-to-model stability.

> The input pack is Kuku's confidential content and is git-ignored. Don't commit it.
