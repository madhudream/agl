"""The loop. This is the whole idea of an agent, in one page.

    Prompt ──► LLM ──► Action ──► Result ──┐
               ▲                           │
               │                           ▼
               └──── Fail ◄── Evaluate ──► Pass ──► Final Answer

The model sees the task and the tools. If it calls tools, we run them and feed
the results back (Action → Result). If it answers, we evaluate. A pass is the
final answer; a fail goes back into the loop as feedback. That is all.

    loop = Loop(llm, tools=Toolbox(read_file), evaluate=judge(llm, "answer cites a file"))
    result = loop.run("what does setup.py do?")
    result.answer, result.passed, result.run.usage()
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .llm import LLM, BudgetExceeded, Reply, Usage, parse_json
from .plugins import Plugins
from .tools import Toolbox

Verdict = dict  # {"passed": bool, "feedback": str, "score": float | None}


class ToolDenied(Exception):
    """Raised by a plugin's on_tool_call to stop a tool from running; the reason goes back to the model as text."""
Evaluator = Callable[[str, "Run"], Verdict]

DEFAULT_SYSTEM = (
    "You are a careful agent. Use the tools when they help; when you have the answer, reply with it "
    "directly and concisely. If the answer must be in a specific format, follow it exactly."
)


@dataclass
class Run:
    """One execution of a Loop: the message history and what it cost."""
    name: str
    task: str
    model: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    messages: list[dict] = field(default_factory=list)
    step: int = 0
    fails: int = 0
    status: str = "running"  # running | pass | fail | budget | max_steps | error
    t0: float = field(default_factory=time.perf_counter)
    ms: int = 0
    _usage: list[Usage] = field(default_factory=list)
    state: dict = field(default_factory=dict)  # graph state when running as a node

    def record(self, reply: Reply) -> None:
        self._usage.append(reply.usage)

    def usage(self) -> dict:
        return {"llm_calls": len(self._usage),
                "prompt_tokens": sum(u.prompt_tokens for u in self._usage),
                "completion_tokens": sum(u.completion_tokens for u in self._usage),
                "cost_usd": round(sum(u.cost_usd for u in self._usage), 6)}

    @property
    def tool_calls(self) -> int:
        return sum(1 for m in self.messages if m.get("role") == "tool")


@dataclass
class Result:
    answer: str
    run: Run
    verdict: Verdict | None = None

    @property
    def passed(self) -> bool:
        return self.run.status == "pass"

    def json(self) -> Any:
        return parse_json(self.answer)

    def __str__(self) -> str:
        return self.answer


class Loop:
    def __init__(self, llm: LLM, *, tools: Toolbox | None = None, system: str = DEFAULT_SYSTEM,
                 evaluate: Evaluator | None = None, plugins: Plugins | None = None, name: str = "loop",
                 max_steps: int = 20, max_fails: int = 2, json_mode: bool = False, parallel_tools: bool = True,
                 json_schema: dict | None = None):
        self.llm = llm
        self.tools = tools or Toolbox()
        self.system = system
        self.evaluate = evaluate
        self.plugins = plugins or Plugins()
        self.name = name
        self.max_steps = max_steps
        self.max_fails = max_fails
        self.json_mode = json_mode
        self.parallel_tools = parallel_tools
        self.json_schema = json_schema  # structured output: the model must return an object matching this schema

    def run(self, task: str, *, context: str | None = None, state: dict | None = None) -> Result:
        run = Run(name=self.name, task=task, model=self.llm.model, state=state or {})
        plugins = self.plugins + run.state["_plugins"] if "_plugins" in run.state else self.plugins
        system = self.system
        if extra := plugins.system_prompt(run):
            system = f"{system}\n\n{extra}"
        run.messages = [{"role": "system", "content": system}]
        if context:
            run.messages.append({"role": "user", "content": f"Context:\n{context}"})
        run.messages.append({"role": "user", "content": task})
        plugins.emit("on_run_start", run)

        answer, verdict = "", None
        try:
            while run.step < self.max_steps:
                run.step += 1
                # ── LLM ───────────────────────────────────────────────────────────
                plugins.emit("on_llm_request", run, run.messages)
                reply = self.llm.chat(run.messages, tools=self.tools.specs or None,
                                      json_mode=self.json_mode and not self.tools.specs,
                                      json_schema=self.json_schema if not self.tools.specs else None)
                run.record(reply)
                run.messages.append(reply.raw_message)
                plugins.emit("on_llm_response", run, reply)

                # ── Action → Result ──────────────────────────────────────────────
                if reply.tool_calls:
                    results = self._run_tools(run, reply.tool_calls, plugins)
                    for call, result in zip(reply.tool_calls, results, strict=True):
                        run.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                    continue

                # ── Evaluate ─────────────────────────────────────────────────────
                answer = reply.text
                verdict = self.evaluate(answer, run) if self.evaluate else {"passed": True, "feedback": ""}
                plugins.emit("on_evaluate", run, verdict)
                if verdict.get("passed"):
                    run.status = "pass"  # ── Final Answer
                    break
                run.fails += 1
                if run.fails > self.max_fails:
                    run.status = "fail"
                    break
                run.messages.append({"role": "user", "content":
                                     f"Your answer did not pass review. Feedback: {verdict.get('feedback', '')}\n"
                                     f"Revise and answer again."})
            else:
                run.status = "max_steps"
        except BudgetExceeded as exc:
            run.status, answer = "budget", answer or f"stopped: {exc}"
        except Exception as exc:
            run.status, answer = "error", answer or f"error: {type(exc).__name__}: {exc}"
        run.ms = int((time.perf_counter() - run.t0) * 1000)
        result = Result(answer=answer, run=run, verdict=verdict)
        plugins.emit("on_run_end", run, answer)
        return result

    def _run_tools(self, run: Run, calls: list[dict], plugins: Plugins) -> list[str]:
        """Run one step's tool calls; several calls in one step run in parallel (exp 0004)."""

        def one(call: dict) -> str:
            try:
                plugins.emit("on_tool_call", run, call["name"], call["arguments"])  # a plugin may raise ToolDenied
            except ToolDenied as exc:
                result = f"denied: {exc}"
                plugins.emit("on_tool_result", run, call["name"], call["arguments"], result)
                return result
            result = self.tools.call(call["name"], call["arguments"])
            plugins.emit("on_tool_result", run, call["name"], call["arguments"], result)
            return result

        if len(calls) == 1 or not self.parallel_tools:
            return [one(c) for c in calls]
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(one, calls))

    def as_node(self, prompt: str | Callable[[dict], str], key: str = "answer",
                context: str | Callable[[dict], str] | None = None) -> Callable[[dict], dict]:
        """Use this loop as a graph node: `prompt` is a str.format template over the state, or a fn(state)."""

        def node(state: dict) -> dict:
            task = prompt(state) if callable(prompt) else prompt.format(**state)
            ctx = context(state) if callable(context) else (context.format(**state) if context else None)
            result = self.run(task, context=ctx, state=state)
            return {key: result.answer, f"{key}_run": {"status": result.run.status, **result.run.usage()}}

        node.__name__ = self.name
        node.kind = "loop"
        return node


# ── Evaluators: deterministic first, LLM-as-judge when you must ──────────────────────────────────

def check(fn: Callable[[str], bool | str], feedback: str = "answer failed the check") -> Evaluator:
    """Deterministic evaluator. `fn` returns True (pass), False (fail) or a str (fail with that feedback)."""

    def evaluate(answer: str, run: Run) -> Verdict:
        r = fn(answer)
        if r is True:
            return {"passed": True, "feedback": "", "score": 1.0}
        return {"passed": False, "feedback": r if isinstance(r, str) else feedback, "score": 0.0}

    return evaluate


def judge(llm: LLM, rubric: str, threshold: float = 0.7, model: str | None = None) -> Evaluator:
    """LLM-as-judge: scores the answer 0..1 against a rubric and explains a fail. Use a different model
    from the worker when you can; the judge is the exam."""

    def evaluate(answer: str, run: Run) -> Verdict:
        prompt = (f"You are a strict reviewer.\n\nTask:\n{run.task}\n\nAnswer:\n{answer}\n\n"
                  f"Rubric:\n{rubric}\n\nReply with JSON only: "
                  '{"score": <0..1>, "passed": <true|false>, "feedback": "<what to fix, one or two sentences>"}')
        reply = llm.chat([{"role": "user", "content": prompt}], json_mode=True, model=model, temperature=0)
        run.record(reply)
        try:
            v = parse_json(reply.text)
            score = float(v.get("score", 0))
            return {"passed": bool(v.get("passed", score >= threshold)) and score >= threshold,
                    "feedback": str(v.get("feedback", "")), "score": score}
        except Exception as exc:
            return {"passed": False, "feedback": f"judge returned unparseable output ({exc})", "score": 0.0}

    return evaluate


def all_of(*evaluators: Evaluator) -> Evaluator:
    """Pass only if every evaluator passes; stops at the first fail (cheap checks first)."""

    def evaluate(answer: str, run: Run) -> Verdict:
        scores = []
        for ev in evaluators:
            v = ev(answer, run)
            if not v.get("passed"):
                return v
            scores.append(v.get("score") or 1.0)
        return {"passed": True, "feedback": "", "score": sum(scores) / len(scores) if scores else 1.0}

    return evaluate
