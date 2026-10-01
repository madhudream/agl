"""The graph. A loop discovers what to do next; a graph pre-determines it.

    Prompt ──► Agent ──┬──► Loop A ──┐
                       ├──► Loop B ──┼──► Review ──► Final
                       └──► Loop C ──┘

Nodes are plain functions `fn(state) -> dict` (or a Loop, or another Graph).
Edges say "when this finishes, go there". The engine runs in waves: every node
whose inputs have all arrived runs in the same wave, in parallel, and writes
disjoint keys into the shared state. Routers pick the next node from the state.

You can draw the graph as text (the diagram is the code):

    g = Graph.from_text('''
        START -> outline
        outline -> write_a, write_b, write_c
        write_a, write_b, write_c -> review
        review ?pass-> END
        review ?fail-> outline
    ''', nodes={"outline": outline, "write_a": ..., "review": review},
         routers={"review": lambda s: "pass" if s["ok"] else "fail"})
    state = g.run({"topic": "graph engineering"}, plugins=default_plugins())
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plugins import Plugins

START, END = "START", "END"
NodeFn = Callable[[dict], dict | None]
RouteFn = Callable[[dict], str]


class StateCollision(Exception):
    """Two nodes in one wave wrote the same key. Parallel branches must write disjoint keys."""


@dataclass
class Node:
    name: str
    fn: NodeFn
    max_visits: int = 3  # > 1 so review → revise cycles work; the engine's max_steps is the hard stop
    on_error: str | None = None  # jump here if the node raises
    retries: int = 0  # re-run the node this many times if it raises (transient model or network errors)
    kind: str = "fn"


@dataclass
class Graph:
    name: str = "graph"
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)
    routers: dict[str, tuple[RouteFn, dict[str, list[str]]]] = field(default_factory=dict)

    # ── build ────────────────────────────────────────────────────────────────────────────────
    def node(self, name: str, fn: NodeFn | Graph, **kw) -> Graph:
        """Add a node: a function of the state, a `loop.as_node(...)`, or a whole Graph."""
        if name in (START, END):
            raise ValueError(f"{name} is reserved")
        if isinstance(fn, Graph):
            fn = fn.as_node()
        kw.setdefault("kind", getattr(fn, "kind", "fn"))
        self.nodes[name] = Node(name=name, fn=fn, **kw)
        return self

    def edge(self, src: str, *dsts: str) -> Graph:
        for d in dsts:
            for end in (src, d):
                if end not in self.nodes and end not in (START, END):
                    raise ValueError(f"unknown node {end!r}")
            self.edges.append((src, d))
        return self

    def router(self, src: str, route: RouteFn, targets: dict[str, str | list[str]]) -> Graph:
        """After `src` runs, `route(state)` returns a label; that label's target(s) run next (END stops)."""
        if src not in self.nodes:
            raise ValueError(f"unknown node {src!r}")
        norm: dict[str, list[str]] = {}
        for label, dst in targets.items():
            dsts = [dst] if isinstance(dst, str) else list(dst)
            for d in dsts:
                if d not in self.nodes and d != END:
                    raise ValueError(f"router target {d!r} (label {label!r}) is unknown")
            norm[label] = dsts
        self.routers[src] = (route, norm)
        return self

    @classmethod
    def from_text(cls, text: str, nodes: dict[str, NodeFn], routers: dict[str, RouteFn] | None = None,
                  name: str = "graph", **node_kw) -> Graph:
        """Parse `a -> b, c` edges and `a ?label-> b` router edges. Node names must exist in `nodes`."""
        g = cls(name=name)
        for n, fn in nodes.items():
            g.node(n, fn, **node_kw)
        pending: dict[str, dict[str, list[str]]] = defaultdict(dict)
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            m = re.match(r"^(\w+)\s*\?(\w+)->\s*(.+)$", line)
            if m:
                pending[m.group(1)][m.group(2)] = [d.strip() for d in m.group(3).split(",")]
                continue
            m = re.match(r"^(.+?)\s*->\s*(.+)$", line)
            if not m:
                raise ValueError(f"cannot parse edge line: {raw!r}")
            srcs = [s.strip() for s in m.group(1).split(",")]
            dsts = [d.strip() for d in m.group(2).split(",")]
            for s in srcs:
                g.edge(s, *dsts)
        for src, targets in pending.items():
            if not routers or src not in routers:
                raise ValueError(f"router edges from {src!r} need a route function in routers=")
            g.router(src, routers[src], targets)
        return g

    # ── compose ──────────────────────────────────────────────────────────────────────────────
    def as_node(self, plugins: Plugins | None = None) -> NodeFn:
        """A whole graph as one node of another graph (it receives and extends the state)."""

        def node(state: dict) -> dict:
            before = set(state)
            out = self.run(dict(state), plugins=plugins)
            return {k: v for k, v in out.items() if k not in before or v is not state.get(k)}

        node.__name__ = self.name
        node.kind = "graph"
        return node

    # ── run ──────────────────────────────────────────────────────────────────────────────────
    def back_edges(self) -> set[tuple[str, str]]:
        """Edges that close a cycle (found by DFS from START, routers included).

        A back edge such as `fix -> assemble` re-triggers its target; it is not an input the
        target must wait for. Everything else is a dependency for fan-in.
        """
        out: dict[str, list[str]] = defaultdict(list)
        for s, d in self.edges:
            out[s].append(d)
        for s, (_r, targets) in self.routers.items():
            out[s].extend(d for ds in targets.values() for d in ds)
        back: set[tuple[str, str]] = set()
        done: set[str] = set()
        stack: list[str] = []

        def dfs(n: str) -> None:
            stack.append(n)
            for d in out[n]:
                if d in stack:
                    back.add((n, d))
                elif d not in done:
                    dfs(d)
            stack.pop()
            done.add(n)

        dfs(START)
        for n in self.nodes:  # nodes not reachable from START still get consistent treatment
            if n not in done:
                dfs(n)
        return back

    def run(self, state: dict | None = None, plugins: Plugins | None = None, max_steps: int = 50,
            checkpoint: str | Path | None = None) -> dict:
        """Run to completion. Errors never raise: they land in state["errors"][node] and the path stops.

        `checkpoint`: a JSON file written after every wave. If it exists when run() starts, the run resumes
        from it: finished nodes are not re-run. Delete the file to start over.
        """
        state = state if state is not None else {}
        plugins = plugins or Plugins()
        lock = threading.Lock()

        def emit(hook, *a):
            with lock:
                plugins.emit(hook, *a)

        back = self.back_edges()
        deps: dict[str, set[str]] = defaultdict(set)
        for s, d in self.edges:
            if d != END and (s, d) not in back:
                deps[d].add(s)
        ever: dict[str, set[str]] = defaultdict(set)  # deps that have fired at least once
        fresh: dict[str, set[str]] = defaultdict(set)  # deps that fired since the node last ran
        runs: dict[str, int] = defaultdict(int)
        path: list[str] = []
        errors: dict[str, str] = state.setdefault("errors", {})
        t0 = time.perf_counter()
        emit("on_graph_start", self, state)

        def ready(jumps: list[str]) -> list[str]:
            """Router jumps + every node whose inputs have all arrived and something new arrived."""
            wave: list[str] = []
            static = [n for n in self.nodes if fresh[n] and deps[n] <= ever[n]]
            for n in jumps + static:
                if n == END or n in wave:
                    continue
                if runs[n] >= self.nodes[n].max_visits:
                    errors.setdefault(n, f"max_visits={self.nodes[n].max_visits} reached")
                    continue
                wave.append(n)
            return wave

        def run_one(name: str) -> tuple[str, dict | None, str | None, int]:
            snapshot = dict(state)
            snapshot["_plugins"] = plugins  # loops running as nodes report into the same trace
            snapshot["_emit"] = lambda kind, **ev: emit("on_event", self, name, kind, ev)  # custom events
            t = time.perf_counter()
            error = None
            for attempt in range(self.nodes[name].retries + 1):
                try:
                    out = self.nodes[name].fn(snapshot)
                    return name, out or {}, None, int((time.perf_counter() - t) * 1000)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}" + (f" (after {attempt + 1} attempts)" if attempt else "")
            return name, None, error, int((time.perf_counter() - t) * 1000)

        def save() -> None:
            if checkpoint:
                doc = {"state": {k: v for k, v in state.items() if not k.startswith("_")}, "runs": runs,
                       "ever": {k: sorted(v) for k, v in ever.items()},
                       "fresh": {k: sorted(v) for k, v in fresh.items()}, "path": path}
                Path(checkpoint).write_text(json.dumps(doc, default=str))

        if checkpoint and Path(checkpoint).exists():  # resume
            saved = json.loads(Path(checkpoint).read_text())
            state.update(saved["state"])
            runs.update(saved["runs"])
            for k, v in saved["ever"].items():
                ever[k] = set(v)
            for k, v in saved["fresh"].items():
                fresh[k] = set(v)
            path.extend(saved["path"])
            errors = state.setdefault("errors", {})
            for n in [n for n in errors if n in self.nodes]:  # nodes that failed last time get another turn
                fresh[n] = set(ever[n]) or {START}
                errors.pop(n)
        else:
            for s, d in self.edges:
                if s == START:
                    ever[d].add(START)
                    fresh[d].add(START)
        wave = ready([])

        while wave:
            if len(path) + len(wave) > max_steps:
                errors.setdefault("engine", f"max_steps={max_steps} reached")
                break
            for n in wave:
                runs[n] += 1
                fresh[n].clear()
                emit("on_node_start", self, n, state)
            if len(wave) == 1:
                results = [run_one(wave[0])]
            else:
                with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                    results = list(pool.map(run_one, wave))

            jumps: list[str] = []
            writes: dict[str, str] = {}
            for name, out, error, ms in results:
                path.append(name)
                keys = [k for k in (out or {}) if not k.startswith("_")]
                for k in keys:
                    if writes.get(k, name) != name:
                        raise StateCollision(f"{name!r} and {writes[k]!r} both wrote {k!r}")
                    writes[k] = name
                    state[k] = out[k]
                emit("on_node_end", self, name, out, error, ms)
                if error:
                    errors[name] = error
                    if self.nodes[name].on_error:
                        jumps.append(self.nodes[name].on_error)
                    continue
                if name in self.routers:
                    route, targets = self.routers[name]
                    label = str(route(state))
                    dsts = targets.get(label)
                    emit("on_route", self, name, label, ", ".join(dsts) if dsts else END)
                    if dsts is None:
                        errors[name] = f"router returned unknown label {label!r}"
                    else:
                        jumps.extend(d for d in dsts if d != END)
                for s, d in self.edges:
                    if s == name and d != END:
                        ever[d].add(name)
                        fresh[d].add(name)
            save()
            wave = ready(jumps)

        state["_path"] = path
        state["_ms"] = int((time.perf_counter() - t0) * 1000)
        emit("on_graph_end", self, state, path)
        return state

    # ── draw ─────────────────────────────────────────────────────────────────────────────────
    def describe(self) -> dict:
        edges = [{"src": s, "dst": d, "label": None} for s, d in self.edges]
        for src, (_r, targets) in self.routers.items():
            edges += [{"src": src, "dst": d, "label": label} for label, dsts in targets.items() for d in dsts]
        return {"name": self.name, "nodes": [{"name": n.name, "kind": n.kind} for n in self.nodes.values()],
                "edges": edges}

    def mermaid(self) -> str:
        shape = {"fn": ("[", "]"), "loop": ("([", "])"), "graph": ("[[", "]]")}
        lines = ["flowchart LR", f"  {START}(( ))", f"  {END}(( ))"]
        for n in self.nodes.values():
            lo, hi = shape.get(n.kind, ("[", "]"))
            lines.append(f"  {n.name}{lo}{n.name}{hi}")
        for e in self.describe()["edges"]:
            arrow = f"-- {e['label']} -->" if e["label"] else "-->"
            lines.append(f"  {e['src']} {arrow} {e['dst']}")
        return "\n".join(lines)

    def layers(self) -> list[list[str]]:
        """Topological layers over the forward edges (routers and back edges ignored), for layout."""
        back = self.back_edges()
        forward = [(s, d) for s, d in self.edges if (s, d) not in back]
        forward += [(s, d) for s, (_r, t) in self.routers.items() for ds in t.values() for d in ds
                    if (s, d) not in back]
        deps = {n: {s for s, d in forward if d == n and s != START} for n in self.nodes}
        placed: set[str] = set()
        out: list[list[str]] = []
        while len(placed) < len(self.nodes):
            layer = [n for n in self.nodes if n not in placed and deps[n] <= placed]
            if not layer:  # cycle through static edges: place the rest
                layer = [n for n in self.nodes if n not in placed]
            out.append(layer)
            placed.update(layer)
        return out

    def excalidraw(self, path: str | None = None) -> dict:
        """Export the graph as an .excalidraw file: a layered, hand-drawn style diagram."""
        from .viz import graph_to_excalidraw
        doc = graph_to_excalidraw(self)
        if path:
            with open(path, "w") as f:
                json.dump(doc, f, indent=1)
        return doc


def fanout(fn: Callable[[Any, dict], Any], over: str, into: str, workers: int = 6) -> NodeFn:
    """Map a function over `state[over]` in parallel and collect into `state[into]`.

    This is the node for "a graph whose fan-out width is only known at run time"
    (one worker per chapter, per file, per question).
    """

    def node(state: dict) -> dict:
        items = list(state.get(over) or [])
        if not items:
            return {into: []}
        with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
            results = list(pool.map(lambda item: fn(item, state), items))
        return {into: results}

    node.__name__ = f"fanout_{over}"
    return node
