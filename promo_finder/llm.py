"""The only place that talks to a model. Swap provider/model in config.yaml.

call_llm(system, prompt, schema) -> validated pydantic object.
 - disk cache keyed on (model, system, prompt): re-runs cost 0 tokens
 - retries with backoff on 429/503, then falls back to the next model
 - JSON is validated with pydantic; on invalid JSON we retry with the error
 - every call is appended to a usage log (tokens, latency, model) for cost estimates
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def _load_env() -> None:
    """Load .env (or any *.env file in the project root) without overriding real env vars."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parent.parent
    for p in [root / ".env", *sorted(root.glob("*.env"))]:
        if p.exists():
            load_dotenv(p, override=False)


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    cached_input_tokens: int = 0   # tokens the cached answers originally cost
    cached_output_tokens: int = 0
    log: list = field(default_factory=list)


@dataclass
class Endpoint:
    name: str
    provider: str          # gemini | anthropic | openai_compat
    model: str
    api_key_env: str
    base_url: str = ""
    key: str = ""
    dead: bool = False     # daily quota gone / bad key / unknown model -> skip for the rest of the run
    cool_until: float = 0  # rate-limited: try others first until this time
    reserve: bool = False  # paid / backup key: used only when every free provider is exhausted or rate-limited


def build_endpoints(cfg: dict) -> list[Endpoint]:
    """`pool:` in config.yaml (several free providers) or the single model + fallback_models."""
    _load_env()
    if cfg.get("pool"):
        raw = cfg["pool"]
    else:
        raw = [{"name": m, "provider": cfg.get("provider", "gemini"), "model": m,
                "api_key_env": cfg.get("api_key_env", "GEMINI_API_KEY"), "base_url": cfg.get("base_url", "")}
               for m in [cfg["model"], *cfg.get("fallback_models", [])]]
    eps = []
    for r in raw:
        env = r.get("api_key_env", "")
        key = "" if env.upper() == "NONE" else os.environ.get(env, "")
        if not key and env.upper() != "NONE":
            continue  # provider not set up (no key in .env) -> silently skipped
        eps.append(Endpoint(r.get("name") or r["model"], r.get("provider", "openai_compat"), r["model"], env,
                            r.get("base_url", ""), key, reserve=bool(r.get("reserve"))))
    return eps


class LLM:
    """strategy: failover    = use the first endpoint until its quota runs out, then the next (most consistent)
                 round_robin = rotate endpoints call by call (spreads free quota over providers)"""

    def __init__(self, cfg: dict, raw_dir: Path | None = None):
        self.cfg = cfg
        self.endpoints = build_endpoints(cfg)
        if not self.endpoints:
            raise RuntimeError("No LLM endpoint has an API key. Add keys to .env (see README) or run with --no-llm")
        self.strategy = cfg.get("strategy", "failover")
        self.offline = bool(cfg.get("cache_only"))  # never call an API: cached answers only
        self._rr = 0
        self.cache_dir = Path(cfg.get("cache_dir", ".cache/llm"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = raw_dir
        if raw_dir:
            raw_dir.mkdir(parents=True, exist_ok=True)
        self.usage = Usage()
        self._last_call: dict[str, float] = {}
        self._clients: dict[str, object] = {}

    def describe(self) -> str:
        return f"{self.strategy}: " + ", ".join(f"{e.name}({e.model})" for e in self.endpoints)

    # ------------------------------------------------------------------ providers
    def _gemini(self, ep: Endpoint, system: str, prompt: str) -> tuple[str, int, int]:
        from google import genai
        from google.genai import types
        if ep.key not in self._clients:
            self._clients[ep.key] = genai.Client(api_key=ep.key)
        conf = types.GenerateContentConfig(system_instruction=system, temperature=self.cfg.get("temperature", 0.2),
                                           response_mime_type="application/json")
        r = self._clients[ep.key].models.generate_content(model=ep.model, contents=prompt, config=conf)
        um = r.usage_metadata
        return r.text or "", (um.prompt_token_count or 0) if um else 0, (um.candidates_token_count or 0) if um else 0

    def _openai_compat(self, ep: Endpoint, system: str, prompt: str, json_mode: bool = True) -> tuple[str, int, int]:
        url = ep.base_url.rstrip("/") + "/chat/completions"
        body = {"model": ep.model, "temperature": self.cfg.get("temperature", 0.2),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", "User-Agent": "promo-finder/1.0"}
        if ep.key:
            headers["Authorization"] = f"Bearer {ep.key}"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 400 and json_mode and "response_format" in detail:
                return self._openai_compat(ep, system, prompt, json_mode=False)  # provider lacks JSON mode
            raise RuntimeError(f"HTTP {e.code}: {detail}") from None
        u = data.get("usage") or {}
        return data["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)

    def _anthropic(self, ep: Endpoint, system: str, prompt: str) -> tuple[str, int, int]:
        """Claude via the official SDK. Errors are re-raised as 'HTTP <code>: ...' so the shared
        pool logic (cooldown on 429, dead on 401 / no credit) treats Claude like every other provider."""
        import anthropic
        if ep.key not in self._clients:
            self._clients[ep.key] = anthropic.Anthropic(api_key=ep.key, max_retries=1, timeout=300)
        client = self._clients[ep.key]
        kw = dict(model=ep.model, max_tokens=16000, system=system, messages=[{"role": "user", "content": prompt}])
        if self.cfg.get("claude_effort"):
            kw["output_config"] = {"effort": self.cfg["claude_effort"]}
        try:
            try:  # server-side refusal fallback: a declined request is re-run on another Claude model
                r = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
            except anthropic.BadRequestError as e:
                if "fallback" not in str(e).lower():
                    raise
                r = client.messages.create(**kw)
        except anthropic.APIStatusError as e:
            code = 503 if e.status_code == 529 else e.status_code  # 529 = overloaded -> treat as temporary
            raise RuntimeError(f"HTTP {code}: {str(e.message)[:300]}") from None
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"timeout / connection error: {e}") from None
        if r.stop_reason == "refusal":
            raise RuntimeError("model declined the request (refusal) -> trying next")
        text = "".join(b.text for b in r.content if b.type == "text")
        return text, r.usage.input_tokens or 0, r.usage.output_tokens or 0

    # ------------------------------------------------------------------ public
    def call(self, system: str, prompt: str, schema: Type[T], tag: str = "call", prefer: str | None = None) -> T:
        schema_json = schema.model_json_schema()
        full_system = (system + "\n\nReturn ONLY valid JSON matching this JSON Schema:\n"
                       + json.dumps(schema_json, separators=(",", ":")))
        key = hashlib.sha256(json.dumps([full_system, prompt]).encode()).hexdigest()[:24]
        cpath = self.cache_dir / f"{key}.json"
        if not cpath.exists():  # answers saved by the first version (key also contained the model name)
            for m in self.cfg.get("legacy_cache_models", []):
                old = self.cache_dir / (hashlib.sha256(json.dumps([m, full_system, prompt]).encode()).hexdigest()[:24] + ".json")
                if old.exists():
                    cpath = old
                    break
        if cpath.exists():
            cj = json.loads(cpath.read_text())
            try:
                obj = schema.model_validate_json(_extract_json(cj["text"]))
                self.usage.cached += 1
                self.usage.cached_input_tokens += cj.get("in", 0)
                self.usage.cached_output_tokens += cj.get("out", 0)
                self.usage.log.append({"tag": tag, "model": cj.get("model"), "in": cj.get("in", 0),
                                       "out": cj.get("out", 0), "sec": 0, "cached": True})
                self._save_raw(tag, prompt, cj["text"], model=cj.get("model", ""), cached=True)
                return obj
            except ValidationError:
                pass

        if self.offline:
            raise CacheMiss(f"cache-only mode: no cached answer for {tag}")
        last_err: Exception | None = None
        tried: set[str] = set()
        while True:
            # re-plan after every failure: a reserve key becomes eligible once the free providers are out
            try:
                order = [e for e in self._order(prefer) if e.name not in tried]
            except RuntimeError as e:
                last_err = last_err or e
                break
            if not order:
                break
            ep = order[0]
            tried.add(ep.name)
            others_left = any(not e.dead and e.name not in tried for e in self.endpoints)
            attempt_prompt = prompt
            for attempt in range(self.cfg.get("max_retries", 4)):
                self._throttle(ep)
                t0 = time.time()
                try:
                    if ep.provider == "gemini":
                        text, tin, tout = self._gemini(ep, full_system, attempt_prompt)
                    elif ep.provider == "anthropic":
                        text, tin, tout = self._anthropic(ep, full_system, attempt_prompt)
                    else:
                        text, tin, tout = self._openai_compat(ep, full_system, attempt_prompt)
                    dt = time.time() - t0
                    self.usage.calls += 1
                    self.usage.input_tokens += tin
                    self.usage.output_tokens += tout
                    self.usage.seconds += dt
                    label = f"{ep.name}:{ep.model}"
                    self.usage.log.append({"tag": tag, "model": label, "in": tin, "out": tout, "sec": round(dt, 1)})
                    obj = schema.model_validate_json(_extract_json(text))
                    cpath.write_text(json.dumps({"model": label, "text": text, "in": tin, "out": tout}))
                    self._save_raw(tag, prompt, text, model=label)
                    return obj
                except ValidationError as e:  # bad JSON shape: tell the model and retry
                    last_err = e
                    attempt_prompt = prompt + f"\n\nYour previous answer was invalid JSON for the schema: {str(e)[:400]}. Fix it."
                except Exception as e:
                    last_err = e
                    msg = str(e)
                    low = msg.lower()
                    if any(c in low for c in ("per day", "perday", "daily", "quota exceeded", "insufficient", "credits", "credit balance")) \
                            or any(c in msg for c in ("HTTP 401", "HTTP 403", "404", "NOT_FOUND", "API_KEY_INVALID")):
                        ep.dead = True  # this provider is out for the rest of the run
                        print(f"  [llm] {ep.name}: {msg[:110]} -> switching provider")
                        break
                    if any(c in low for c in ("413", "too large", "context length", "context_length", "maximum context",
                                              "request too large", "tokens per minute")) and "429" not in msg:
                        print(f"  [llm] {ep.name}: request too big for this provider -> trying next")
                        break
                    if any(c in msg for c in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500", "502")) \
                            or "timed out" in low or "timeout" in low:
                        if others_left:  # don't sit on a rate limit when other providers are free
                            ep.cool_until = time.time() + self.cfg.get("cooldown_seconds", 90)
                            print(f"  [llm] {ep.name}: rate limited -> pausing it {self.cfg.get('cooldown_seconds', 90)}s, trying next provider")
                            break
                        wait = min(60, 5 * 2 ** attempt)
                        m = re.search(r"retry in ([\d.]+)s", msg) or re.search(r"try again in ([\d.]+)s", msg)
                        if m:
                            wait = min(90, float(m.group(1)) + 1)
                        print(f"  [llm] {ep.name}: rate limited, waiting {wait:.0f}s")
                        time.sleep(wait)
                        continue
                    print(f"  [llm] {ep.name}: error {msg[:140]} -> trying next")
                    break
        raise RuntimeError(f"All LLM endpoints failed for {tag}: {last_err}")

    def _order(self, prefer: str | None = None) -> list[Endpoint]:
        alive = [e for e in self.endpoints if not e.dead]
        if not alive:
            raise RuntimeError("Every LLM endpoint is out of quota. Add a reserve/paid key in config.yaml, wait for "
                               "the daily reset, or use --cache-only / --no-llm.")
        now = time.time()
        free = [e for e in alive if not e.reserve]
        reserve = [e for e in alive if e.reserve]
        if not any(e.cool_until <= now for e in free) and any(e.cool_until <= now for e in reserve):
            # every free provider is out of quota or rate-limited -> send the rest of the work to the reserve key
            if not getattr(self, "_reserve_announced", False):
                print(f"  [llm] free providers exhausted -> switching to reserve: {', '.join(e.name for e in reserve)}")
                self._reserve_announced = True
            return [e for e in reserve if e.cool_until <= now] + [e for e in reserve if e.cool_until > now]
        alive = free or reserve
        if all(e.cool_until > now for e in alive):  # everyone is cooling down: wait for the first to be free
            wait = min(e.cool_until for e in alive) - now
            print(f"  [llm] all providers rate-limited, waiting {wait:.0f}s")
            time.sleep(max(0, wait))
            now = time.time()
        ready = [e for e in alive if e.cool_until <= now]
        alive = ready + [e for e in alive if e.cool_until > now]
        pref = [e for e in alive if e.name == prefer and e.cool_until <= now]
        if pref:  # e.g. the editor review / series profile always use the same model when it is available
            return pref + [e for e in alive if e is not pref[0]]
        alive = [e for e in alive if not e.reserve] or alive
        if self.strategy == "round_robin":
            i = self._rr % len(alive)
            self._rr += 1
            return alive[i:] + alive[:i]
        return alive

    def _throttle(self, ep: Endpoint) -> None:
        gap = self.cfg.get("min_seconds_between_calls", 0)
        wait = self._last_call.get(ep.name, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last_call[ep.name] = time.time()

    def _save_raw(self, tag: str, prompt: str, text: str, model: str = "", cached: bool = False) -> None:
        if not self.raw_dir:
            return
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag)
        (self.raw_dir / f"{safe}.json").write_text(json.dumps(
            {"tag": tag, "model": model, "cached": cached, "prompt": prompt, "response": text}, indent=2, ensure_ascii=False))


def list_models(cfg: dict) -> None:
    """Print the models each configured provider offers with your key (to fill config.yaml)."""
    for ep in build_endpoints(cfg):
        try:
            if ep.provider == "gemini":
                from google import genai
                client = genai.Client(api_key=ep.key)  # keep a reference: the pager needs an open client
                names = [m.name.replace("models/", "") for m in client.models.list()]
            elif ep.provider == "anthropic":
                import anthropic
                names = [m.id for m in anthropic.Anthropic(api_key=ep.key).models.list()]
            else:
                req = urllib.request.Request(ep.base_url.rstrip("/") + "/models",
                                             headers={"Authorization": f"Bearer {ep.key}", "User-Agent": "promo-finder/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    names = [m["id"] for m in json.loads(r.read()).get("data", [])]
            ok = "OK " if ep.model in names else "?? "
            print(f"{ok}{ep.name}: configured '{ep.model}' | {len(names)} models available, e.g. {names[:12]}")
        except Exception as e:
            print(f"ERR {ep.name}: {str(e)[:150]}")


class CacheMiss(RuntimeError):
    pass


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    return m.group(0) if m else text


def ping(cfg: dict) -> None:
    """One tiny JSON request per provider (~60 tokens each) to prove key + model + JSON mode work."""
    from pydantic import BaseModel as _BM

    class Pong(_BM):
        ok: bool

    for ep in build_endpoints(cfg):
        one = dict(cfg, pool=[{"name": ep.name, "provider": ep.provider, "model": ep.model,
                               "api_key_env": ep.api_key_env, "base_url": ep.base_url}],
                   cache_dir=str(Path(cfg.get("cache_dir", ".cache/llm")) / "_ping"), max_retries=1)
        t0 = time.time()
        try:
            LLM(one).call("Answer in JSON.", f'Return {{"ok": true}} ({time.time()})', Pong, tag="ping")
            print(f"OK   {ep.name:12s} {ep.model}  ({time.time() - t0:.1f}s)")
        except Exception as e:
            print(f"FAIL {ep.name:12s} {ep.model}  {str(e)[:160]}")
