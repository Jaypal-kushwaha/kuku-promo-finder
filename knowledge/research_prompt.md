# Research prompt → knowledge pack

Run this prompt in a tool that can **search the web** and cite sources, e.g. Gemini Deep Research, ChatGPT (search /
deep research) or Perplexity. Don't use a plain API model: without web access it will invent statistics.
Save the JSON it returns as `knowledge/promo_knowledge.json`, then check it with:

    .venv/bin/python -m promo_finder.knowledge knowledge/promo_knowledge.json

The pipeline only sends a compact slice of the pack to the judge (decision rules, hook ranking, cliffhanger
findings, microdrama insights, weak techniques). That slice is capped at `knowledge_max_chars` in config.yaml, so
the pack can be long without costing tokens.

---

You are an expert researcher specializing in short-form video performance, viewer psychology, storytelling and
social media analytics.

Research what ACTUALLY works and what DOES NOT work when creating high-performing promotional videos, particularly
for fictional microdramas, short dramas, TikTok, Instagram Reels and YouTube Shorts.

Use real-world evidence, not just personal opinions or generic content-creation advice.

Investigate these areas:

1. HOOKS: Which opening techniques produce the strongest viewer attention? Compare shocking dialogue, questions,
   visual surprises, conflict, mystery, emotional reactions, reveals and curiosity gaps.
2. STORYTELLING: Evaluate stakes, big questions, unexpected but logical twists (head fakes), rehooks and unresolved endings.
3. RETENTION: What makes viewers continue watching after the first 3 seconds? Investigate the first 5–10 seconds,
   pacing, information gaps, escalating tension and narrative progression.
4. CLIFFHANGERS: Which types of unresolved endings are most effective? Compare unanswered questions, interrupted
   reveals, sudden threats, betrayals and unexpected arrivals.
5. STANDALONE CONTEXT: How much background information does a new viewer need before becoming emotionally invested?
6. WEAK TECHNIQUES: Identify common approaches that reduce retention, create confusion, weaken curiosity or make
   viewers scroll away.
7. PERFORMANCE METRICS: Investigate available evidence on hook retention, average watch time, completion rate,
   rewatch rate, shares and engagement.

RESEARCH RULES:
- Prioritize peer-reviewed research, platform-published research, credible industry studies and large-scale performance datasets.
- Use real performance data wherever available.
- Prefer studies involving actual viewer behaviour over creator opinions.
- Distinguish correlation from proven causation.
- Separate findings for educational videos from entertainment and fictional drama.
- Do not treat viral creator claims as scientific evidence.
- Do not invent statistics, rankings or benchmarks.
- Include source links and publication dates.
- Evaluate the four-step storytelling loop (Stakes, Big Question, Head Fake, Rehook), Interrupt Theory, Four S's
  (Subject, Stakes, Speed, Simplicity), Triple Hook and Lock-in Zone. Determine which principles have supporting
  evidence and which remain hypotheses.

OUTPUT REQUIREMENTS: Produce a compact research knowledge pack for another LLM. Return only valid JSON:

{
  "high_performing_principles": [{"principle": "", "why_it_works": "", "evidence": "", "confidence": "high/medium/low", "best_application": ""}],
  "weak_or_risky_principles": [{"technique": "", "why_it_underperforms": "", "evidence": "", "exceptions": ""}],
  "hook_rankings": [],
  "retention_findings": [],
  "cliffhanger_findings": [],
  "microdrama_specific_insights": [],
  "important_tradeoffs": [],
  "sources": [{"claim": "", "source": "", "url": "", "year": ""}],
  "llm_decision_rules": []
}

FINAL OBJECTIVE: Create a small, evidence-backed reference that helps another LLM make better decisions when
selecting promotional clips. Prioritize actionable findings over lengthy explanations. Do not pretend there is one
universally best hook. Explain which techniques work best under which circumstances. Optimize the output for minimum
token consumption without sacrificing important evidence.
