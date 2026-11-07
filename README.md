# 🎬 Promo Finder

**Give it the episode scripts of a microdrama. It returns the best 20–60 second promo clips, ranked in the order to post them.**

For every promo you get:
- the episode and the exact start and end time of each part
- the **hook** (what grabs the viewer in the first 3 seconds)
- the **cliffhanger** (the unresolved moment it ends on)
- **why it works**, and why it's in that position
- the **promo script**: every line and action the viewer will see

---

## 1. One-time setup

You need **Python 3.10 or newer**. In a terminal:

```bash
git clone https://github.com/<your-username>/kuku-promo-finder.git
cd kuku-promo-finder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
On Windows, use `.venv\Scripts\` wherever this README says `.venv/bin/`.

**Add your AI keys.** Copy the template and fill in the keys you have:
```bash
cp .env.example .env        # Windows: copy .env.example .env
```
Open `.env` in any text editor and paste each key after its `=`. One key is enough; leave the rest empty.

| Name in `.env` | Where to get it | Cost |
|---|---|---|
| `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3` | https://aistudio.google.com/apikey (one key per Google account) | free |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY_2` | https://console.anthropic.com | paid |
| `GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY` | console.groq.com · console.mistral.ai · openrouter.ai | free backups |

Keys are tried in the order listed in `config.yaml`. When one runs out of quota, the next takes over automatically.
Check your keys with `.venv/bin/python run.py --ping` (one tiny request per key).

No key at all? It still works: see "free mode" in step 3.

---

## 2. Put the episode scripts in a folder

Create one folder per show and put **one `.txt` script per episode** inside it:

```
kuku-promo-finder/
└── my_show/                          ← your input folder (any name)
    ├── episode-001.txt
    ├── episode-002.txt
    └── ...
```
The scripts use the standard format, with a `Start: (mm:ss.xx) | End: (mm:ss.xx)` time on every line.

---

## 3. Run it

```bash
.venv/bin/python run.py "my_show"
```
Use the name of your folder, in quotes if it contains spaces. A 50-episode show takes about **5–8 minutes**. You'll see progress like `judging episodes 1-4…`, and it's done when it prints `wrote …promos.html`.

| Want to… | Type |
|---|---|
| Normal run (uses AI) | `.venv/bin/python run.py "my_show"` |
| **Free mode** (no AI, no key, 2 seconds) | `.venv/bin/python run.py "my_show" --no-llm` |
| Check your keys work | `.venv/bin/python run.py --ping` |
| Finish using only saved AI answers (0 tokens) | `.venv/bin/python run.py "my_show" --cache-only` |
| Use one specific model | `.venv/bin/python run.py "my_show" --model gemini-3.5-flash-lite` |

If the free AI limit runs out mid-run, the tool **still finishes**: the episodes it couldn't send to the AI get rule-based picks. Run the same command again later and only the missing parts go to the AI; finished parts are reused for free.

---

## 4. See the results

Results go to `outputs/<your folder name>/`:

```
outputs/my_show/
├── promos.html   ← OPEN THIS: visual report, top 10 as cards (double-click to open in a browser)
├── promos.md     ← same report as text
├── promos.csv    ← spreadsheet (Excel / Google Sheets)
├── promos.json   ← all data
└── llm_raw/      ← every question sent to the AI and its raw answer
```

### Prefer an app?
```bash
.venv/bin/streamlit run app.py
```
It opens in your browser. Upload the episode files (or pick a folder, or open a previous run) and click **Find promos**. You can read each promo's script, tick the ones to approve, and download your approved list.

---


## How it works, briefly

1. **Read:** every episode is turned into a list of timed lines, actions and sounds.
2. **Understand the show:** the AI reads the episode summaries to find the genre and the main characters, then picks the matching **genre playbook** from `genres.yaml` (which kinds of promos to post first).
3. **Shortlist:** simple rules spot intense moments (slaps, threats, reveals, betrayals) and mark 3 possible clips per episode.
4. **Judge:** the AI reviews each shortlisted clip, tightens the start and end, and writes the hook, cliffhanger and why. It can only pick moments that exist in the script, so it can't invent times.
5. **Check and rank:** every clip is checked (20–60 s, clean cut, strong opening), then put in posting order. The AI compares the best 20 head-to-head to choose the top 10.

**Settings you can change:** `config.yaml` sets which AI models to use (any provider; add a paid key as `reserve: true`) and the clip length. `genres.yaml` holds the genre playbooks, and `knowledge/` holds the editing rules given to the AI.
