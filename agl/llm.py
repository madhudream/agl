"""One LLM client for the whole framework.

The OpenAI SDK against any OpenAI-compatible model API (AGL_BASE_URL). Every call
goes through `LLM.chat`, so cost, tokens, latency and caching are measured in one
place. "What gets measured gets improved."

    llm = LLM()                      # model from AGL_MODEL, key from AGL_API_KEY
    reply = llm.chat([{"role": "user", "content": "hi"}])
    reply.text, reply.tool_calls, reply.usage.cost_usd
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import OpenAI

from .env import load_env

load_env()

BASE_URL = os.environ.get("AGL_BASE_URL", "https://api.openai.com/v1")  # any OpenAI-compatible model API
DEFAULT_MODEL = os.environ.get("AGL_MODEL", "gpt-5.4-mini")  # the worker: cheap enough to run the exam every time
SMART_MODEL = os.environ.get("AGL_MODEL_SMART", "gpt-6-astra")  # the specialist: one node that needs it, measured
JUDGE_MODEL = os.environ.get("AGL_MODEL_JUDGE", "gpt-5.5")  # the judge: a different model from the worker; the exam
_DIRECT_OPENAI = "api.openai.com" in BASE_URL


class BudgetExceeded(RuntimeError):
    """Raised by the Meter when the run's dollar budget is spent."""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    ms: int = 0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Reply:
    """What the model said: text, tool calls, and what it cost."""
    text: str
    tool_calls: list[dict]  # [{"id", "name", "arguments": dict}]
    usage: Usage
    raw_message: dict  # the assistant message, ready to append to history
    finish_reason: str = ""

    def json(self) -> Any:
        return parse_json(self.text)


@dataclass
class Meter:
    """Thread-safe totals for one process. budget_usd=0 means unlimited."""
    calls: int = 0
    cached: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    budget_usd: float = field(default_factory=lambda: float(os.environ.get("AGL_BUDGET_USD", "0") or 0))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, u: Usage) -> None:
        with self._lock:
            self.calls += 1
            if u.cached:
                self.cached += 1
            else:
                self.prompt_tokens += u.prompt_tokens
                self.completion_tokens += u.completion_tokens
                self.cost_usd += u.cost_usd
            if self.budget_usd and self.cost_usd >= self.budget_usd:
                raise BudgetExceeded(f"spent ${self.cost_usd:.4f} >= budget ${self.budget_usd:.2f}")

    def as_dict(self) -> dict:
        return {"calls": self.calls, "cached": self.cached, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "cost_usd": round(self.cost_usd, 6)}

    def reset(self) -> None:
        with self._lock:
            self.calls = self.cached = self.prompt_tokens = self.completion_tokens = 0
            self.cost_usd = 0.0


METER = Meter()


class Cache:
    """sha256(model, messages, params) -> response JSON, in one SQLite file.

    A repeated eval run is free and deterministic. Off unless AGL_CACHE points to a path.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, t REAL)")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def key(**parts) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, k: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, k: str, v: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (k, json.dumps(v), time.time()))


class LLM:
    """Thin, measured wrapper over `openai.OpenAI().chat.completions.create`."""

    def __init__(self, model: str = DEFAULT_MODEL, *, api_key: str | None = None, base_url: str = BASE_URL,
                 temperature: float | None = None, max_tokens: int | None = None, cache: str | Path | None = None,
                 meter: Meter = METER, retries: int = 3, extra_body: dict | None = None,
                 reasoning: str | None = None):
        key = api_key or os.environ.get("AGL_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("no API key: set AGL_API_KEY in .env")
        self.client = OpenAI(base_url=base_url, api_key=key,
                             default_headers={"HTTP-Referer": "https://github.com/madhudream/agl", "X-Title": "agl"})
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.meter = meter
        self.retries = retries
        direct = "api.openai.com" in base_url
        # ask the model API to report the dollar cost of every call (gateways do; the direct API has no such field)
        self.extra_body = {**({} if direct else {"usage": {"include": True}}), **(extra_body or {})}
        # reasoning effort: "none" | "low" | "medium" | "high"; None = provider default
        reasoning = reasoning or os.environ.get("AGL_REASONING", "low")  # exp 0001/0003: equal score, 15-29% cheaper
        if reasoning and reasoning != "none" and direct:
            self.extra_body["reasoning_effort"] = reasoning  # the direct API's spelling of the same knob
        elif reasoning == "none" and not direct:
            self.extra_body["reasoning"] = {"enabled": False}
        elif reasoning and not direct:
            self.extra_body["reasoning"] = {"effort": reasoning}
        cache = cache if cache is not None else os.environ.get("AGL_CACHE")
        self.cache = Cache(cache) if cache else None

    def with_model(self, model: str) -> LLM:
        """Same client and meter, different model. Cheap to call."""
        clone = object.__new__(LLM)
        clone.__dict__.update(self.__dict__)
        clone.model = model
        return clone

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None, json_mode: bool = False,
             model: str | None = None, temperature: float | None = None, max_tokens: int | None = None,
             tool_choice: str | dict | None = None, json_schema: dict | None = None) -> Reply:
        model = model or self.model
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice
        if json_schema:  # structured output: {"name": ..., "schema": {...}} or a bare JSON schema
            schema = json_schema if "schema" in json_schema else {"name": "reply", "schema": json_schema}
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"strict": True, **schema}}
        elif json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if (t := temperature if temperature is not None else self.temperature) is not None:
            kwargs["temperature"] = t
        if (m := max_tokens or self.max_tokens) is not None:
            kwargs["max_tokens"] = m

        key = Cache.key(**kwargs) if self.cache else None
        if key and (hit := self.cache.get(key)):
            reply = _to_reply(hit, cached=True)
            self.meter.add(reply.usage)
            return reply

        t0 = time.perf_counter()
        resp = self._create(kwargs)
        data = resp.model_dump()
        data["_ms"] = int((time.perf_counter() - t0) * 1000)
        if key:
            self.cache.put(key, data)
        reply = _to_reply(data, cached=False)
        self.meter.add(reply.usage)
        return reply

    def _create(self, kwargs: dict):
        delay = 1.0
        for attempt in range(self.retries + 1):
            try:
                return self.client.chat.completions.create(extra_body=self.extra_body, **kwargs)
            except Exception as exc:  # rate limit / 5xx / transient network
                status = getattr(exc, "status_code", None)
                has_knob = any(k.startswith("reasoning") for k in self.extra_body)
                if status == 400 and "reasoning" in str(exc).lower() and has_knob:
                    # this model will not take the reasoning knob: drop it for this client and retry once
                    self.extra_body = {k: v for k, v in self.extra_body.items() if not k.startswith("reasoning")}
                    continue
                if attempt == self.retries or (status and 400 <= status < 500 and status != 429):
                    raise
                time.sleep(delay)
                delay *= 2

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        model = model or os.environ.get("AGL_EMBED_MODEL", "text-embedding-3-small")
        resp = self.client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]


def _to_reply(data: dict, *, cached: bool) -> Reply:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_raw": fn.get("arguments")}
        calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": args})
    u = data.get("usage") or {}
    details = u.get("completion_tokens_details") or {}
    usage = Usage(prompt_tokens=u.get("prompt_tokens") or 0, completion_tokens=u.get("completion_tokens") or 0,
                  reasoning_tokens=details.get("reasoning_tokens") or 0,
                  cost_usd=0.0 if cached else float(u.get("cost") or 0.0), cached=cached, ms=data.get("_ms", 0))
    raw = {"role": "assistant", "content": msg.get("content")}
    if msg.get("tool_calls"):
        raw["tool_calls"] = [{"id": tc["id"], "type": "function",
                              "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
                             for tc in msg["tool_calls"]]
    return Reply(text=msg.get("content") or "", tool_calls=calls, usage=usage, raw_message=raw,
                 finish_reason=choice.get("finish_reason") or "")


def parse_json(text: str) -> Any:
    """Tolerant JSON parse: strips code fences and surrounding prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        t = t.rstrip()
        t = t.removesuffix("```")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = t.find(open_c), t.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON found in: {text[:200]!r}")
