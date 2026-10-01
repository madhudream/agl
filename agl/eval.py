"""Evals: run a task file, score it, print an autoresearch-style summary, append results.tsv.

A task is one JSON line:
  {"id": "sum", "task": "...", "tools": ["calc"], "expect": {"contains": "42"}}
  {"id": "essay", "task": "...", "expect": {"judge": "rubric text", "min_score": 0.7}}
  {"id": "plan", "graph": "examples.02_graph_fanout:build", "state": {...}, "expect": {"key": "final", "contains": "x"}}

`expect` checks (deterministic ones first, all must pass):
  contains / not_contains / equals / regex / json_keys / min_len / max_len / judge (LLM, scores 0..1)

Summary (grep-able, like autoresearch's train.py):
  score, pass_rate, cost_usd, tokens_mean, steps_mean, ms_p50, ms_p95, RESULT
"""
from __future__ import annotations

import importlib
import json
import re
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .llm import JUDGE_MODEL, LLM, METER, parse_json
from .loop import DEFAULT_SYSTEM, Loop
from .plugins import Plugins, Trace
from .tools import Toolbox


@dataclass
class Score:
    id: str
    passed: bool
    score: float
    ms: int
    cost_usd: float
    tokens: int
    steps: int
    status: str
    detail: str
    answer: str


def load_tasks(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _resolve(dotted: str):
    mod, _, attr = dotted.partition(":")
    return getattr(importlib.import_module(mod), attr)


def grade(answer: str, expect: dict, task: str, judge_llm: LLM | None) -> tuple[bool, float, str]:
    """Deterministic checks first; the LLM judge last and only if everything else passed."""
    a = answer or ""
    for key, val in expect.items():
        if key == "contains" and not all(v.lower() in a.lower() for v in _as_list(val)):
            return False, 0.0, f"missing {val!r}"
        if key == "not_contains" and any(v.lower() in a.lower() for v in _as_list(val)):
            return False, 0.0, f"should not contain {val!r}"
        if key == "equals" and a.strip() != str(val).strip():
            return False, 0.0, f"expected {val!r}, got {a[:80]!r}"
        if key == "regex" and not re.search(val, a, re.S):
            return False, 0.0, f"regex {val!r} did not match"
        if key == "min_len" and len(a) < val:
            return False, 0.0, f"too short: {len(a)} < {val}"
        if key == "max_len" and len(a) > val:
            return False, 0.0, f"too long: {len(a)} > {val}"
        if key == "json_keys":
            try:
                obj = parse_json(a)
            except ValueError as exc:
                return False, 0.0, f"not JSON: {exc}"
            if missing := [k for k in val if k not in obj]:
                return False, 0.0, f"JSON missing keys {missing}"
    if "judge" in expect:
        if judge_llm is None:
            return True, 1.0, "judge skipped (no judge model)"
        prompt = (f"Score this answer against the rubric. Task:\n{task}\n\nAnswer:\n{a[:6000]}\n\nRubric:\n"
                  f"{expect['judge']}\n\nReply with JSON only: {{\"score\": <0..1>, \"reason\": \"<one sentence>\"}}")
        reply = judge_llm.chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0)
        try:
            v = parse_json(reply.text)
            s = float(v.get("score", 0))
            return s >= expect.get("min_score", 0.7), s, str(v.get("reason", ""))
        except (ValueError, TypeError) as exc:
            return False, 0.0, f"judge unparseable: {exc}"
    return True, 1.0, "ok"


def _as_list(v):
    return v if isinstance(v, list) else [v]


def run_task(t: dict, llm: LLM, tools: dict[str, object], judge_llm: LLM | None, plugins: Plugins) -> Score:
    t0 = time.perf_counter()
    before = METER.as_dict()
    status, steps, answer = "pass", 0, ""
    try:
        if "graph" in t:
            g = _resolve(t["graph"])(llm) if callable(_resolve(t["graph"])) else _resolve(t["graph"])
            state = g.run(dict(t.get("state") or {}), plugins=plugins)
            answer = str(state.get(t.get("expect", {}).get("key", "final"), ""))
            steps = len(state.get("_path", []))
            status = "pass" if not state.get("errors") else "error"
        else:
            tb = Toolbox(*[tools[n] for n in t.get("tools", []) if n in tools])
            loop = Loop(llm.with_model(t["model"]) if t.get("model") else llm, tools=tb, name=t["id"],
                        system=t.get("system") or DEFAULT_SYSTEM, plugins=plugins,
                        max_steps=t.get("max_steps", 12))
            r = loop.run(t["task"], context=t.get("context"))
            answer, steps, status = r.answer, r.run.step, r.run.status
    except Exception as exc:  # noqa: BLE001 - an eval must record the crash, not die
        status, answer = "crash", f"{type(exc).__name__}: {exc}"
    after = METER.as_dict()
    passed, score, detail = grade(answer, t.get("expect", {}), t.get("task", ""), judge_llm)
    if status in ("crash", "error"):
        passed, score = False, 0.0
    return Score(id=t["id"], passed=passed, score=round(score, 3), ms=int((time.perf_counter() - t0) * 1000),
                 cost_usd=round(after["cost_usd"] - before["cost_usd"], 6),
                 tokens=(after["prompt_tokens"] + after["completion_tokens"])
                 - (before["prompt_tokens"] + before["completion_tokens"]),
                 steps=steps, status=status, detail=detail[:200], answer=answer[:400])


def summarize(scores: list[Score]) -> dict:
    ms = sorted(s.ms for s in scores) or [0]
    n = len(scores)
    return {
        "score": round(100 * sum(s.score for s in scores) / n, 1) if n else 0.0,
        "pass_rate": round(100 * sum(s.passed for s in scores) / n, 1) if n else 0.0,
        "n": n,
        "cost_usd": round(sum(s.cost_usd for s in scores), 4),
        "tokens_mean": int(statistics.mean(s.tokens for s in scores)) if n else 0,
        "steps_mean": round(statistics.mean(s.steps for s in scores), 2) if n else 0,
        "ms_p50": ms[len(ms) // 2],
        "ms_p95": ms[min(len(ms) - 1, int(len(ms) * 0.95))],
        "crashes": sum(s.status == "crash" for s in scores),
        "RESULT": "OK" if n and not any(s.status == "crash" for s in scores) else ("CRASH" if n else "EMPTY"),
    }


def print_summary(summary: dict, scores: list[Score]) -> None:
    print("\nid                    pass  score   steps   ms      $        detail")
    for s in scores:
        print(f"{s.id:<21} {'PASS' if s.passed else 'FAIL':<5} {s.score:<6} {s.steps:<7} {s.ms:<7} "
              f"{s.cost_usd:<8.5f} {s.status if s.status != 'pass' else ''} {s.detail[:60]}")
    print("---")
    for k, v in summary.items():
        print(f"{k + ':':<14}{v}")


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "nogit"


def append_results(path: str | Path, summary: dict, model: str, description: str, status: str = "pending") -> None:
    p = Path(path)
    header = "commit\tmodel\tscore\tpass_rate\tcost_usd\ttokens_mean\tms_p50\tstatus\tdescription\n"
    if not p.exists():
        p.write_text(header)
    with open(p, "a") as f:
        f.write(f"{git_commit()}\t{model}\t{summary['score']}\t{summary['pass_rate']}\t{summary['cost_usd']}\t"
                f"{summary['tokens_mean']}\t{summary['ms_p50']}\t{status}\t{description}\n")


def run_suite(tasks_path: str | Path, llm: LLM, tools: dict[str, object], *, judge: bool = True,
              trace: str | Path = "traces/eval.jsonl", only: list[str] | None = None,
              workers: int = 4) -> tuple[dict, list[Score]]:
    from concurrent.futures import ThreadPoolExecutor
    tasks = load_tasks(tasks_path)
    if only:
        tasks = [t for t in tasks if t["id"] in only]
    judge_llm = llm.with_model(JUDGE_MODEL) if judge else None
    plugins = Plugins(Trace(trace))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        scores = list(pool.map(lambda t: run_task(t, llm, tools, judge_llm, plugins), tasks))
    summary = summarize(scores)
    Path(trace).with_suffix(".scores.json").write_text(json.dumps([asdict(s) for s in scores], indent=1))
    return summary, scores
