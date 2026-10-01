"""agl command line.

  agl run "task" [--model m] [--tools calc,read_file,...] [--skills]     one loop
  agl graph examples/02_graph_fanout.py [--state '{"topic": "x"}']        run a graph file (needs build(llm))
  agl draw examples/02_graph_fanout.py [--excalidraw out] [--mermaid]     draw a graph
  agl viz traces/run.jsonl [-o out.html]                                  trace → HTML
  agl eval evals/tasks.jsonl [--only id,id] [--no-judge] [--desc text]    run the suite, append results.tsv
  agl models [filter]                                                     list available models (prices when reported)
  agl serve [--port 8790] [--graphs a.py,b.py]                            HTTP: POST /run, POST /graph, GET /graphs
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import webbrowser
from pathlib import Path

from . import LLM, Loop, Toolbox, default_plugins
from .plugins import Skills
from .std_tools import STD_TOOLS


def _load_module(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(Path(path).resolve().parent.parent))
    spec.loader.exec_module(mod)
    return mod


def cmd_run(a):
    llm = LLM(a.model) if a.model else LLM()
    tools = Toolbox(*[STD_TOOLS[n] for n in (a.tools.split(",") if a.tools else []) if n in STD_TOOLS])
    plugins = default_plugins(verbose=not a.quiet)
    if a.skills:
        plugins.add(Skills())
    if a.memory:
        from .memory import Memory
        mem = Memory(a.memory)
        plugins.add(mem)
        for t in mem.tools:
            tools.add(t)
    r = Loop(llm, tools=tools, plugins=plugins).run(a.task)
    print(r.answer)
    if a.memory:
        mem.flush()


def cmd_graph(a):
    mod = _load_module(a.file)
    llm = LLM(a.model) if a.model else LLM()
    g = mod.build(llm)
    state = g.run(json.loads(a.state) if a.state else {}, plugins=default_plugins(verbose=not a.quiet))
    key = a.key or "final"
    print(state.get(key) if key in state else json.dumps({k: v for k, v in state.items() if not k.startswith("_")},
                                                           indent=1, default=str)[:4000])


def cmd_draw(a):
    mod = _load_module(a.file)
    g = mod.build(LLM()) if hasattr(mod, "build") else mod.graph
    if a.excalidraw:
        g.excalidraw(a.excalidraw)
        print(f"wrote {a.excalidraw}")
    if a.mermaid or not a.excalidraw:
        print(g.mermaid())


def cmd_viz(a):
    from .viz import read_trace, trace_to_html
    events = read_trace(a.trace)
    out = Path(a.out or Path(a.trace).with_suffix(".html"))
    out.write_text(trace_to_html(events, title=f"agl trace: {Path(a.trace).name}"))
    print(f"wrote {out} ({len(events)} events)")
    if a.open:
        webbrowser.open(out.resolve().as_uri())


def cmd_eval(a):
    from .eval import append_results, print_summary, run_suite
    llm = LLM(a.model) if a.model else LLM()
    summary, scores = run_suite(a.tasks, llm, STD_TOOLS, judge=not a.no_judge,
                                only=a.only.split(",") if a.only else None, workers=a.workers)
    print_summary(summary, scores)
    if a.desc:
        append_results("results.tsv", summary, llm.model, a.desc)
        print("appended to results.tsv")


def cmd_models(a):
    """GET {AGL_BASE_URL}/models. Gateways report prices and context sizes; the direct API reports ids only."""
    import os
    import urllib.request

    from .llm import BASE_URL
    req = urllib.request.Request(f"{BASE_URL.rstrip('/')}/models", headers={
        "Authorization": f"Bearer {os.environ.get('AGL_API_KEY') or os.environ.get('OPENAI_API_KEY', '')}"})
    with urllib.request.urlopen(req) as r:
        data = json.load(r)["data"]
    rows = []
    for m in data:
        if a.filter and a.filter.lower() not in m["id"].lower():
            continue
        p = m.get("pricing") or {}
        rows.append((m["id"], float(p.get("prompt") or 0) * 1e6, float(p.get("completion") or 0) * 1e6,
                     m.get("context_length"), "tools" if "tools" in (m.get("supported_parameters") or []) else ""))
    rows.sort(key=lambda r: (r[1] + r[2], r[0]))
    print(f"{'model':<48} {'$/M in':>8} {'$/M out':>8} {'ctx':>9}  tools")
    for r in rows[: a.limit]:
        print(f"{r[0]:<48} {r[1]:>8.3f} {r[2]:>8.3f} {str(r[3] or '-'):>9}  {r[4]}")


def cmd_serve(a):
    from .serve import serve
    serve(host=a.host, port=a.port, graphs=a.graphs.split(",") if a.graphs else [])


def main(argv=None):
    p = argparse.ArgumentParser(prog="agl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run", help="run one loop")
    s.add_argument("task")
    s.add_argument("--model")
    s.add_argument("--tools", help="comma list from std_tools")
    s.add_argument("--skills", action="store_true", help="append skills/*.md to the system prompt")
    s.add_argument("--memory", metavar="USER_ID", help="long-term memory for this user id")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("graph", help="run a graph file")
    s.add_argument("file")
    s.add_argument("--state", help="JSON initial state")
    s.add_argument("--key", help="state key to print (default: final)")
    s.add_argument("--model")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(fn=cmd_graph)

    s = sub.add_parser("draw", help="draw a graph")
    s.add_argument("file")
    s.add_argument("--excalidraw", metavar="OUT")
    s.add_argument("--mermaid", action="store_true")
    s.set_defaults(fn=cmd_draw)

    s = sub.add_parser("viz", help="render a trace to HTML")
    s.add_argument("trace")
    s.add_argument("-o", "--out")
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_viz)

    s = sub.add_parser("eval", help="run the eval suite")
    s.add_argument("tasks", nargs="?", default="evals/tasks.jsonl")
    s.add_argument("--model")
    s.add_argument("--only")
    s.add_argument("--no-judge", action="store_true")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--desc", help="append a results.tsv row with this description")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("models", help="list available models")
    s.add_argument("filter", nargs="?")
    s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_models)

    s = sub.add_parser("serve", help="serve loops and graphs over HTTP")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8790)
    s.add_argument("--graphs", help="comma list of files exposing build(llm)")
    s.set_defaults(fn=cmd_serve)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
