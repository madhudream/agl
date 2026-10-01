"""`agl serve`: the loop and the graphs over HTTP, so any app (Next.js, Workers, Swift) can call them.

    uv run agl serve --port 8790 --graphs examples/graph_fanout.py,examples/course_builder.py

    POST /run     {"task": "...", "tools": ["calc"], "model": "...", "system": "...", "user_id": "..."}
                  -> {"answer", "status", "steps", "usage"}
    POST /graph   {"name": "fanout-edit-review", "state": {"topic": "..."}}
                  -> the final state (keys starting with "_" and "errors" included)
    GET  /graphs  -> [{"name", "nodes", "edges"}]       GET /health -> {"ok": true, "meter": {...}}

Standard library only. One process, one thread per request; the graph engine does its own fan-out.
`user_id` turns on memory for that id. Bind to 127.0.0.1 and put a real gateway in front for production.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .llm import LLM, METER
from .loop import DEFAULT_SYSTEM, Loop
from .plugins import Plugins, Trace
from .std_tools import STD_TOOLS
from .tools import Toolbox


class Service:
    """Everything the handler needs, built once. `graphs` maps graph name -> Graph."""

    def __init__(self, llm: LLM | None = None, graphs: dict | None = None, trace: str | Path = "traces/serve.jsonl"):
        self.llm = llm or LLM()
        self.graphs = graphs or {}
        self.plugins = Plugins(Trace(trace))
        self._memories: dict[str, object] = {}

    def memory(self, user_id: str):
        if user_id not in self._memories:
            from .memory import Memory
            self._memories[user_id] = Memory(user_id)
        return self._memories[user_id]

    def run(self, req: dict) -> dict:
        tools = Toolbox(*[STD_TOOLS[n] for n in req.get("tools", []) if n in STD_TOOLS])
        plugins = self.plugins
        if uid := req.get("user_id"):
            mem = self.memory(uid)
            plugins = plugins + Plugins(mem)
            for t in mem.tools:
                tools.add(t)
        llm = self.llm.with_model(req["model"]) if req.get("model") else self.llm
        loop = Loop(llm, tools=tools, system=req.get("system") or DEFAULT_SYSTEM, plugins=plugins,
                    max_steps=int(req.get("max_steps", 20)), name=req.get("name", "serve"))
        r = loop.run(req["task"], context=req.get("context"))
        return {"answer": r.answer, "status": r.run.status, "steps": r.run.step, "usage": r.run.usage(),
                "run_id": r.run.id}

    def graph(self, req: dict) -> dict:
        g = self.graphs.get(req.get("name", ""))
        if g is None:
            raise KeyError(f"unknown graph {req.get('name')!r}; have {list(self.graphs)}")
        state = g.run(dict(req.get("state") or {}), plugins=self.plugins)
        return {k: v for k, v in state.items() if k != "_plugins"}

    def describe(self) -> list[dict]:
        return [g.describe() for g in self.graphs.values()]


def load_graphs(paths: list[str], llm: LLM) -> dict:
    """Each file must expose `build(llm) -> Graph`; the graph's own name is its key."""
    import importlib.util
    import sys
    out = {}
    for p in paths:
        spec = importlib.util.spec_from_file_location(Path(p).stem, p)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(Path(p).resolve().parent.parent))
        spec.loader.exec_module(mod)
        g = mod.build(llm)
        out[g.name] = g
    return out


def make_handler(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict | list) -> None:
            data = json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True, "meter": METER.as_dict()})
            if self.path == "/graphs":
                return self._send(200, svc.describe())
            self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/run":
                    return self._send(200, svc.run(req))
                if self.path == "/graph":
                    return self._send(200, svc.graph(req))
                self._send(404, {"error": "not found"})
            except KeyError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - the server must answer, never die
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        def log_message(self, fmt, *args):  # quiet; the Trace plugin is the log
            pass

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8790, graphs: list[str] | None = None) -> None:
    llm = LLM()
    svc = Service(llm, load_graphs(graphs or [], llm))
    httpd = ThreadingHTTPServer((host, port), make_handler(svc))
    print(f"agl serve on http://{host}:{port}  graphs={list(svc.graphs)}  model={llm.model}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
