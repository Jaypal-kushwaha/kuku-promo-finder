"""Streamlit UI: upload a show, find promos, review them, export the approved list.

    streamlit run app.py
"""
import json
import os
import tempfile
from pathlib import Path

import streamlit as st

from promo_finder.compress import beat_sheet
from promo_finder.parser import parse_folder
from promo_finder.pipeline import ROOT, run

st.set_page_config(page_title="Promo Finder", page_icon="🎬", layout="wide")
st.title("🎬 Microdrama Promo Finder")
st.caption("Reads episode screenplays → finds 20–60 s promos with a hook in the first 3 s and a cliffhanger cut → "
           "ranks them in posting order. An editor approves the final list.")

with st.sidebar:
    st.header("1 · Input")
    src = st.radio("Episodes", ["Upload .txt files", "Local folder", "Open a previous run"], index=0)
    folder, uploads, prev = None, None, None
    if src == "Upload .txt files":
        uploads = st.file_uploader("One screenplay .txt per episode", type=["txt"], accept_multiple_files=True)
        show_name = st.text_input("Show name", "uploaded_show")
    elif src == "Local folder":
        default = next((str(p) for p in ROOT.iterdir() if p.is_dir() and any(p.glob("episode-*.txt"))), "")
        folder = st.text_input("Folder path", default)
    else:
        runs = sorted(ROOT.glob("outputs/*/promos.json"))
        prev = st.selectbox("Run", runs, format_func=lambda p: p.parent.name) if runs else None

    st.header("2 · Model")
    use_llm = st.toggle("Use LLM judge (off = rules-only baseline, 0 tokens)", value=True)
    model_src = st.radio("Models", ["Free-provider pool from config.yaml", "One specific model"], index=0)
    provider, model, base_url, key, strategy = "gemini", "", "", "", "round_robin"
    if model_src.startswith("Free"):
        strategy = st.selectbox("Strategy", ["round_robin", "failover"],
                                help="round_robin rotates providers per batch; failover sticks to one until its quota ends")
    else:
        provider = st.selectbox("Provider", ["gemini", "openai_compat"], help="openai_compat = Groq, OpenRouter, Ollama, OpenAI, …")
        model = st.text_input("Model", "gemini-3.5-flash")
        base_url = st.text_input("Base URL (openai_compat only)", "") if provider == "openai_compat" else ""
        key = st.text_input("API key (optional — otherwise read from .env)", type="password")
    stitch_n = st.slider("Stitched cross-episode promos", 0, 8, 5)
    go = st.button("Find promos", type="primary", disabled=(src == "Open a previous run"))


def _run(path: Path, out: Path) -> dict:
    llm_over: dict = {"strategy": strategy}
    if model:
        key_env = "PROMO_UI_API_KEY" if key else ("GEMINI_API_KEY" if provider == "gemini" else "NONE")
        if key:
            os.environ["PROMO_UI_API_KEY"] = key
        llm_over.update({"pool": [{"name": "ui", "provider": provider, "model": model, "base_url": base_url,
                                   "api_key_env": key_env}], "editor_model": "ui"})
    override = {"llm": llm_over, "promo": {"stitched_promos": stitch_n}}
    with st.status("Running pipeline…", expanded=True) as status:
        res = run(path, out, use_llm=use_llm, log=lambda m: st.write(m), config_override=override)
        status.update(label="Done", state="complete")
    return res


result, src_folder = None, None
if go:
    try:
        if uploads:
            tmp = Path(tempfile.mkdtemp()) / show_name
            tmp.mkdir(parents=True)
            for f in uploads:
                (tmp / f.name).write_bytes(f.getvalue())
            result, src_folder = _run(tmp, ROOT / "outputs" / f"ui_{show_name}"), tmp
        elif folder and Path(folder).is_dir():
            result, src_folder = _run(Path(folder), None), Path(folder)
        else:
            st.error("Upload files or give a valid folder.")
    except Exception as e:
        st.exception(e)
    if result:
        st.session_state["result"], st.session_state["src"] = result, str(src_folder)
elif prev:
    st.session_state["result"] = json.loads(Path(prev).read_text())
    st.session_state.setdefault("src", "")

result = st.session_state.get("result")
if not result:
    st.info("Pick an input in the sidebar and press **Find promos** (or open a previous run).")
    st.stop()

prof, stats = result["profile"], result["stats"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Episodes", result["episodes"])
c2.metric("Promos", len(result["promos"]))
c3.metric("LLM tokens per full run (in/out)", f"{stats.get('full_run_input_tokens', stats['llm_input_tokens']):,} / "
          f"{stats.get('full_run_output_tokens', stats['llm_output_tokens']):,}")
c4.metric("Run time", f"{stats['seconds']}s")
st.markdown(f"**Genre playbook:** `{prof['primary_genre']}` + `{prof['secondary_genre'] or '—'}` · "
            f"**Premise:** {prof['premise']}")
if result.get("editor_notes"):
    st.markdown(f"_Editor strategy: {result['editor_notes']}_")

eps = {}
src = st.session_state.get("src")
if src and Path(src).is_dir():
    eps = {e.number: e for e in parse_folder(src)}

st.subheader("Promos in posting order")
approved = []
for p in result["promos"]:
    s = p["scores"]
    segs = " + ".join(f"E{x['episode']:02d} {x['start_ts']}–{x['end_ts']}" for x in p["segments"])
    flag = " ⚠️" if [w for w in p.get("warnings", []) if "snapped" not in w] else ""
    with st.expander(f"#{p['rank']} · {s['final']} · {p['title']} · {segs} · {p['duration']:.0f}s{flag}", expanded=p["rank"] <= 3):
        a, b = st.columns([3, 1])
        with a:
            st.markdown(f"**Hook (0–3 s):** {p['hook']}\n\n**Cliffhanger:** {p['cliffhanger']}\n\n"
                        f"**Why it works:** {p['why_it_works']}")
            if p.get("why_post_first"):
                st.markdown(f"**Why post it #{p['rank']}:** {p['why_post_first']}")
            if p.get("standalone_issue"):
                st.markdown(f"**New-viewer gap:** {p['standalone_issue']}")
            for w in p.get("warnings", []):
                st.caption("check: " + w)
        with b:
            st.markdown(f"Archetype: **{p['archetype_name']}**  \nHook {s['hook']}/5 · Cliff {s['cliffhanger']}/5 · "
                        f"Standalone {s['standalone']}/5  \nType: {p['type']} · source: {p['source']}")
            if st.checkbox("Approve", key=f"ok_{p['id']}", value=p["rank"] <= 10):
                approved.append(p)
        if eps:
            for x in p["segments"]:
                if x["episode"] in eps:
                    st.code(beat_sheet(eps[x["episode"]], x["start"], x["end"] - 0.01), language=None)

st.download_button("Download approved promos (JSON)", json.dumps(approved, indent=2, ensure_ascii=False),
                   file_name="approved_promos.json", mime="application/json")
st.download_button("Download all results (JSON)", json.dumps(result, indent=2, ensure_ascii=False),
                   file_name="promos.json", mime="application/json")
