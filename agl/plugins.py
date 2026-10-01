"""Plugins: everything around the loop is a hook ("everything is a plugin").

A plugin is any object with some of these methods. The loop and the graph call
them at the right moments; a plugin that does not define a hook is skipped.

    on_run_start(run)                 on_run_end(run, result)
    on_llm_request(run, messages)     on_llm_response(run, reply)
    on_tool_call(run, name, args)     on_tool_result(run, name, args, result)
    on_evaluate(run, verdict)
    on_node_start(graph, node, state) on_node_end(graph, node, out, error, ms)
    on_route(graph, router, label, target)
    on_graph_start(graph, state)      on_graph_end(graph, state, path)
    on_event(graph, node, kind, ev)   # a node called state["_emit"](kind, **ev)
    system_prompt(run) -> str | None  # append text to the system prompt (skills, memory)

Built-ins: Trace (JSONL), Console (pretty print), Budget (hard stop), Skills (procedural memory).
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm import METER, BudgetExceeded

HOOKS = ("on_run_start", "on_run_end", "on_llm_request", "on_llm_response", "on_tool_call", "on_tool_result",
         "on_evaluate", "on_node_start", "on_node_end", "on_route", "on_graph_start", "on_graph_end", "on_event")


class Plugins:
    """An ordered list of plugins. `emit` fans a hook out to every plugin that has it."""

    def __init__(self, *plugins: Any):
        self.items: list[Any] = list(plugins)

    def add(self, *plugins: Any) -> Plugins:
        self.items.extend(plugins)
        return self

    def emit(self, hook: str, *args, **kwargs) -> None:
        for p in self.items:
            fn = getattr(p, hook, None)
            if fn:
                fn(*args, **kwargs)

    def system_prompt(self, run) -> str:
        parts = []
        for p in self.items:
            fn = getattr(p, "system_prompt", None)
            if fn and (text := fn(run)):
                parts.append(text)
        return "\n\n".join(parts)

    def __add__(self, other: Plugins) -> Plugins:
        return Plugins(*self.items, *[p for p in other.items if p not in self.items])

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


@dataclass
class Trace:
    """Append every event as one JSON line. The trace viewer reads this file."""
    path: str | Path = field(default_factory=lambda: os.environ.get("AGL_TRACE", "traces/run.jsonl"))

    def __post_init__(self):
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, kind: str, **ev) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "kind": kind, **ev}, default=str) + "\n")

    # loop hooks
    def on_run_start(self, run):
        self.write("run_start", run=run.id, name=run.name, task=run.task[:500], model=run.model)

    def on_llm_response(self, run, reply):
        self.write("llm", run=run.id, step=run.step, text=reply.text[:2000],
                   tool_calls=[{"name": c["name"], "arguments": c["arguments"]} for c in reply.tool_calls],
                   **reply.usage.as_dict())

    def on_tool_result(self, run, name, args, result):
        self.write("tool", run=run.id, step=run.step, name=name, arguments=args, result=str(result)[:2000])

    def on_evaluate(self, run, verdict):
        self.write("evaluate", run=run.id, step=run.step, **verdict)

    def on_run_end(self, run, result):
        self.write("run_end", run=run.id, steps=run.step, ms=run.ms, status=run.status,
                   answer=str(result)[:2000], **run.usage())

    # graph hooks
    def on_graph_start(self, graph, state):
        self.write("graph_start", graph=graph.name, nodes=list(graph.nodes), edges=graph.describe()["edges"])

    def on_node_start(self, graph, node, state):
        self.write("node_start", graph=graph.name, node=node)

    def on_node_end(self, graph, node, out, error, ms):
        self.write("node_end", graph=graph.name, node=node, ms=ms, error=error,
                   keys=[k for k in (out or {}) if not k.startswith("_")])

    def on_route(self, graph, router, label, target):
        self.write("route", graph=graph.name, router=router, label=label, target=target)

    def on_graph_end(self, graph, state, path):
        self.write("graph_end", graph=graph.name, path=path, errors=state.get("errors", {}), **METER.as_dict())

    def on_event(self, graph, node, kind, ev):
        self.write(kind, graph=graph.name, node=node, **ev)


@dataclass
class Console:
    """Human-readable progress on stderr. Set verbose=False for a one-line-per-step view."""
    verbose: bool = True
    out: Any = field(default_factory=lambda: sys.stderr)

    def _p(self, s: str):
        print(s, file=self.out, flush=True)

    def on_run_start(self, run):
        self._p(f"\n┌─ loop {run.name} [{run.model}]  task: {run.task[:90]!r}")

    def on_llm_response(self, run, reply):
        u = reply.usage
        head = f"│ {run.step:>2} llm  {u.ms:>5}ms  {u.prompt_tokens}+{u.completion_tokens} tok  ${u.cost_usd:.5f}"
        if reply.tool_calls:
            head += "  → " + ", ".join(f"{c['name']}({_short(c['arguments'])})" for c in reply.tool_calls)
        elif reply.text and self.verbose:
            head += f"  “{reply.text[:80].replace(chr(10), ' ')}”"
        self._p(head)

    def on_tool_result(self, run, name, args, result):
        if self.verbose:
            self._p(f"│    tool {name} ⇒ {str(result)[:100].replace(chr(10), ' ')}")

    def on_evaluate(self, run, verdict):
        mark = "✓ PASS" if verdict.get("passed") else "✗ FAIL"
        self._p(f"│    evaluate {mark}  {verdict.get('feedback', '')[:100]}")

    def on_run_end(self, run, result):
        u = run.usage()
        self._p(f"└─ {run.status} in {run.step} steps, {run.ms}ms, ${u['cost_usd']:.4f}")

    def on_graph_start(self, graph, state):
        self._p(f"\n╔═ graph {graph.name}: {len(graph.nodes)} nodes")

    def on_node_start(self, graph, node, state):
        self._p(f"║ ▶ {node}")

    def on_node_end(self, graph, node, out, error, ms):
        self._p(f"║ ■ {node} {ms}ms" + (f"  ERROR {error[:80]}" if error else ""))

    def on_route(self, graph, router, label, target):
        self._p(f"║ ⤷ {router} --{label}--> {target}")

    def on_graph_end(self, graph, state, path):
        self._p(f"╚═ done: {' → '.join(path)}  ${METER.cost_usd:.4f} total")

    def on_event(self, graph, node, kind, ev):
        if kind == "evaluate":
            mark = "✓ PASS" if ev.get("passed") else "✗ FAIL"
            self._p(f"║   {node}: {mark} score={ev.get('score')} {ev.get('feedback', '')[:90]}")
        elif self.verbose:
            self._p(f"║   {node}: {kind} {_short(ev, 90)}")


@dataclass
class Approval:
    """Human in the loop: tools named in `guarded` run only if `ask(name, args)` returns True.

    `ask` defaults to a terminal prompt. In a server, pass a function that checks an allow-list or a
    queue. A denial goes back to the model as text ("denied: ..."), so the loop continues without the action.
    """
    guarded: tuple[str, ...] = ("shell", "write_file")
    ask: Any = None

    def on_tool_call(self, run, name, args):
        from .loop import ToolDenied
        if name not in self.guarded:
            return
        ask = self.ask or (lambda n, a: input(f"allow {n}({_short(a, 120)})? [y/N] ").strip().lower() == "y")
        if not ask(name, args):
            raise ToolDenied(f"{name} was not approved by the operator")


@dataclass
class Compact:
    """Context compaction: when the history grows past `max_chars`, shorten old tool results in place.

    Deterministic and free: every tool result older than the last `keep_recent` is cut to `head` characters
    plus a note saying what was removed. The model keeps the gist and the loop stops paying for the whole
    file on every later call. Summaries by a model are a drop-in alternative; this is the floor.
    """
    max_chars: int = 60_000
    keep_recent: int = 2
    head: int = 400

    def on_llm_request(self, run, messages):
        total = sum(len(str(m.get("content") or "")) for m in messages)
        if total <= self.max_chars:
            return
        tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        for i in tool_idx[:-self.keep_recent] if self.keep_recent else tool_idx:
            c = messages[i].get("content") or ""
            if len(c) > self.head + 80:
                messages[i]["content"] = c[:self.head] + f"\n... [compacted: {len(c) - self.head} characters removed]"


def _short(d: dict, n: int = 60) -> str:
    s = ", ".join(f"{k}={json.dumps(v, default=str)}" for k, v in d.items())
    return s if len(s) <= n else s[:n] + "…"


@dataclass
class Budget:
    """Stop a run when it has spent more than `usd` or taken more than `steps`."""
    usd: float = 0.5
    steps: int = 30

    def on_llm_response(self, run, reply):
        if run.usage()["cost_usd"] > self.usd:
            raise BudgetExceeded(f"run {run.name} spent ${run.usage()['cost_usd']:.3f} > ${self.usd}")
        if run.step > self.steps:
            raise BudgetExceeded(f"run {run.name} took {run.step} steps > {self.steps}")


@dataclass
class Skills:
    """Procedural memory, Claude Code style: every `skills/*.md` is appended to the system prompt.

    A skill is a short markdown file: how to do one kind of task well. Edit the
    file, the agent behaves differently. No retraining, no code.
    """
    dir: str | Path = "skills"
    only: list[str] | None = None

    def system_prompt(self, run) -> str | None:
        d = Path(self.dir)
        if not d.is_dir():
            return None
        files = sorted(d.glob("*.md"))
        if self.only:
            files = [f for f in files if f.stem in self.only]
        if not files:
            return None
        return "# Skills\n\n" + "\n\n".join(f"## {f.stem}\n{f.read_text().strip()}" for f in files)


def default_plugins(verbose: bool = True) -> Plugins:
    """The 'standard' preset: trace + console + budget. `Plugins()` is the 'minimal' preset."""
    return Plugins(Trace(), Console(verbose=verbose), Budget())
