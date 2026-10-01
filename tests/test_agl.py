from __future__ import annotations

import json

import pytest

from agl import END, START, Graph, Loop, Plugins, StateCollision, Toolbox, all_of, check, fanout, judge, tool
from agl.llm import parse_json
from agl.plugins import Skills, Trace

# ── tools ────────────────────────────────────────────────────────────────────────────────────

def test_tool_schema_from_signature_and_docstring():
    @tool
    def add(a: int, b: int = 2, tags: list[str] | None = None) -> int:
        """Add two numbers.

        Args:
            a: first number
            b: second number
        """
        return a + b

    spec = add.spec["function"]
    assert spec["name"] == "add" and spec["description"] == "Add two numbers."
    assert spec["parameters"]["properties"]["a"] == {"type": "integer", "description": "first number"}
    assert spec["parameters"]["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}
    assert spec["parameters"]["required"] == ["a"]
    assert add(a=1) == 3


def test_toolbox_errors_are_text_not_exceptions():
    def boom(x: int) -> int:
        """Boom."""
        raise ValueError("no")

    tb = Toolbox(boom)
    assert tb.call("boom", {"x": 1}).startswith("error: ValueError")
    assert tb.call("missing", {}).startswith("error: unknown tool")
    assert tb.call("boom", {"y": 1}).startswith("error: bad arguments")


# ── loop ─────────────────────────────────────────────────────────────────────────────────────

def test_loop_runs_tools_then_answers(fake):
    def add(a: int, b: int) -> int:
        """Add."""
        return a + b

    llm = fake([[("add", {"a": 2, "b": 3})], "The sum is 5."])
    loop = Loop(llm, tools=Toolbox(add))
    r = loop.run("add 2 and 3")
    assert r.passed and r.answer == "The sum is 5." and r.run.step == 2 and r.run.tool_calls == 1
    # the tool result went back into the history
    assert any(m.get("role") == "tool" and m["content"] == "5" for m in r.run.messages)


def test_loop_evaluate_fail_then_pass(fake):
    llm = fake(["draft", "final"])
    loop = Loop(llm, evaluate=check(lambda a: a == "final", "say final"))
    r = loop.run("x")
    assert r.passed and r.answer == "final" and r.run.fails == 1
    assert "Feedback: say final" in llm.calls[1][-1]["content"]


def test_loop_gives_up_after_max_fails(fake):
    llm = fake(["a", "b", "c", "d"])
    loop = Loop(llm, evaluate=check(lambda a: False), max_fails=2)
    r = loop.run("x")
    assert not r.passed and r.run.status == "fail" and r.run.fails == 3


def test_judge_parses_json_verdict(fake):
    worker = fake(["my answer"])
    j = fake([json.dumps({"score": 0.9, "passed": True, "feedback": ""})])
    r = Loop(worker, evaluate=judge(j, "be right")).run("q")
    assert r.passed and r.verdict["score"] == 0.9


def test_all_of_short_circuits(fake):
    seen = []

    def ev(name, ok):
        def f(a, run):
            seen.append(name)
            return {"passed": ok, "feedback": name}
        return f

    r = Loop(fake(["x"]), evaluate=all_of(ev("a", True), ev("b", False), ev("c", True)), max_fails=0).run("q")
    assert seen == ["a", "b"] and not r.passed


def test_skills_plugin_appends_to_system_prompt(fake, tmp_path):
    (tmp_path / "style.md").write_text("Write plainly.")
    llm = fake(["ok"])
    Loop(llm, plugins=Plugins(Skills(tmp_path))).run("q")
    assert "## style\nWrite plainly." in llm.calls[0][0]["content"]


def test_trace_plugin_writes_jsonl(fake, tmp_path):
    p = tmp_path / "t.jsonl"
    Loop(fake(["ok"]), plugins=Plugins(Trace(p))).run("q")
    kinds = [json.loads(line)["kind"] for line in p.read_text().splitlines()]
    assert kinds == ["run_start", "llm", "evaluate", "run_end"]


# ── graph ────────────────────────────────────────────────────────────────────────────────────

def test_graph_waves_run_in_parallel_and_merge():
    import threading
    order = []
    lock = threading.Lock()

    def mk(name, delay=0.0):
        def fn(s):
            import time
            time.sleep(delay)
            with lock:
                order.append(name)
            return {name: s["x"] + 1}
        return fn

    g = Graph("t")
    for n in ("a", "b", "c", "d"):
        g.node(n, mk(n, 0.05 if n == "b" else 0))
    g.edge(START, "a").edge("a", "b", "c").edge("b", "d").edge("c", "d").edge("d", END)
    s = g.run({"x": 1})
    assert s["_path"][0] == "a" and set(s["_path"][1:3]) == {"b", "c"} and s["_path"][3] == "d"
    assert s["a"] == s["b"] == s["c"] == s["d"] == 2 and not s["errors"]


def test_graph_router_cycle_and_max_visits():
    n = {"i": 0}

    def work(s):
        n["i"] += 1
        return {"n": n["i"]}

    g = Graph("cycle").node("work", work).node("review", lambda s: {"ok": s["n"] >= 2})
    g.edge(START, "work").edge("work", "review")
    g.router("review", lambda s: "pass" if s["ok"] else "fail", {"pass": END, "fail": "work"})
    s = g.run({})
    assert s["_path"] == ["work", "review", "work", "review"] and s["n"] == 2


def test_graph_from_text_dsl():
    def f(k):
        return lambda s: {k: True}

    g = Graph.from_text("""
        START -> a            # fan out
        a -> b, c
        b, c -> d
        d ?ok-> END
        d ?retry-> a
    """, nodes={"a": f("a"), "b": f("b"), "c": f("c"), "d": f("d")}, routers={"d": lambda s: "ok"})
    assert len(g.edges) == 5 and "d" in g.routers
    s = g.run({})
    assert s["_path"][-1] == "d" and all(s[k] for k in "abcd")
    assert "d -- ok --> END" in g.mermaid()


def test_graph_state_collision_is_a_bug():
    g = Graph("x").node("a", lambda s: {"k": 1}).node("b", lambda s: {"k": 2})
    g.edge(START, "a", "b")
    with pytest.raises(StateCollision):
        g.run({})


def test_graph_errors_land_in_state_and_on_error_jumps():
    def bad(s):
        raise RuntimeError("nope")

    g = Graph("e").node("bad", bad, on_error="fix").node("fix", lambda s: {"fixed": True})
    g.edge(START, "bad")
    s = g.run({})
    assert "RuntimeError" in s["errors"]["bad"] and s["fixed"] and s["_path"] == ["bad", "fix"]


def test_fanout_maps_in_parallel():
    node = fanout(lambda item, s: item * s["m"], over="items", into="out")
    assert node({"items": [1, 2, 3], "m": 10}) == {"out": [10, 20, 30]}


def test_loop_as_graph_node(fake):
    loop = Loop(fake(["hello world"]), name="writer")
    g = Graph("g").node("write", loop.as_node("write about {topic}", key="draft")).edge(START, "write")
    s = g.run({"topic": "graphs"})
    assert s["draft"] == "hello world" and s["draft_run"]["status"] == "pass" and g.nodes["write"].kind == "loop"


def test_subgraph_as_node():
    inner = Graph("inner").node("x", lambda s: {"y": s["a"] * 2}).edge(START, "x")
    outer = Graph("outer").node("in", inner).node("z", lambda s: {"z": s["y"] + 1}).edge(START, "in").edge("in", "z")
    s = outer.run({"a": 5})
    assert s["y"] == 10 and s["z"] == 11 and outer.nodes["in"].kind == "graph"


def test_excalidraw_export_has_nodes_and_arrows(tmp_path):
    g = Graph("d").node("a", lambda s: {}).node("b", lambda s: {}).edge(START, "a").edge("a", "b").edge("b", END)
    doc = g.excalidraw(tmp_path / "g.excalidraw")
    types = [e["type"] for e in doc["elements"]]
    assert types.count("rectangle") == 2 and types.count("ellipse") == 2 and types.count("arrow") == 3
    assert json.loads((tmp_path / "g.excalidraw").read_text())["type"] == "excalidraw"


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": [1,2]} done') == {"a": [1, 2]}


def test_back_edge_retriggers_without_blocking_fan_in():
    calls = {"n": 0}

    def checker(s):
        calls["n"] += 1
        return {"ok": calls["n"] >= 2}

    g = Graph.from_text("""
        START -> a
        a -> assemble
        assemble -> checker
        checker ?ok-> END
        checker ?fail-> fix
        fix -> assemble
    """, nodes={"a": lambda s: {"a": 1}, "assemble": lambda s: {"built": calls["n"]}, "checker": checker,
                "fix": lambda s: {"fixed": True}}, routers={"checker": lambda s: "ok" if s["ok"] else "fail"})
    assert g.back_edges() == {("fix", "assemble")}
    s = g.run({})
    assert s["_path"] == ["a", "assemble", "checker", "fix", "assemble", "checker"] and not s["errors"]
    assert g.layers() == [["a"], ["assemble"], ["checker"], ["fix"]]


def test_memory_plugin_offline(tmp_path, fake):
    from agl.memory import DefaultBackend, Memory
    extractor = fake([json.dumps({"facts": ["Hanu teaches in Kansas City.", "Hanu prefers plain English."]})])
    mem = Memory("t:user", backend=DefaultBackend(extractor, db_path=tmp_path / "m.sqlite"))
    assert mem.tools[1](fact="Hanu's course app is written in Python.") == "stored"
    assert mem.tools[1](fact="Hanu's course app is written in Python.") == "already known"
    assert any("Python" in r["text"] for r in mem.search("python course"))
    worker = fake(["ok"])
    Loop(worker, plugins=Plugins(mem)).run("where do I teach?")
    mem.flush()  # the extractor ran in the background: two more facts
    assert len(mem.all()) == 3 and "# Memory" in worker.calls[0][0]["content"]
    block, n = mem.backend.recall("Kansas", "t:user", 800)
    assert n >= 1 and "Kansas" in block


def test_service_run_and_graph(fake, tmp_path):
    from agl.serve import Service
    g = Graph("g").node("a", lambda s: {"out": s["x"] * 2}).edge(START, "a")
    svc = Service(fake(["42"]), {"g": g}, trace=tmp_path / "t.jsonl")
    r = svc.run({"task": "answer 42", "tools": ["calc"]})
    assert r["answer"] == "42" and r["status"] == "pass" and r["usage"]["llm_calls"] == 1
    assert svc.graph({"name": "g", "state": {"x": 21}})["out"] == 42
    assert svc.describe()[0]["name"] == "g"
    with pytest.raises(KeyError):
        svc.graph({"name": "nope"})


def test_parallel_tool_calls_keep_order(fake):
    import time

    def slow(x: int) -> int:
        """Slow."""
        time.sleep(0.2 if x == 1 else 0.0)
        return x

    llm = fake([[("slow", {"x": 1}), ("slow", {"x": 2}), ("slow", {"x": 3})], "done"])
    t = time.perf_counter()
    r = Loop(llm, tools=Toolbox(slow)).run("go")
    assert time.perf_counter() - t < 0.5  # ran together, not 0.2 + 0 + 0 sequential... parallel anyway
    tools = [m for m in r.run.messages if m.get("role") == "tool"]
    assert [m["content"] for m in tools] == ["1", "2", "3"] and [m["tool_call_id"] for m in tools] == ["c0", "c1", "c2"]


def test_grep_tool_accepts_a_file_path():
    from agl.std_tools import grep
    out = grep(pattern=r"^\s*def ", path="evals/fixtures/sample.py")
    assert out.count("\n") + 1 == 7 and "sample.py:" in out
    assert "sample.py" in grep(pattern="class Ledger", path="evals/fixtures", glob="*.py")


def test_approval_plugin_denies_guarded_tools(fake):
    from agl import Approval

    def shell(command: str) -> str:
        """Run."""
        return "ran " + command

    llm = fake([[("shell", {"command": "rm -rf /"})], "stopped"])
    r = Loop(llm, tools=Toolbox(shell), plugins=Plugins(Approval(ask=lambda n, a: False))).run("clean up")
    tool_msgs = [m for m in r.run.messages if m.get("role") == "tool"]
    assert tool_msgs[0]["content"].startswith("denied:") and r.answer == "stopped"


def test_compact_plugin_shortens_old_tool_results(fake):
    from agl import Compact
    big = "x" * 5000

    def read(path: str) -> str:
        """Read."""
        return big

    llm = fake([[("read", {"path": "a"})], [("read", {"path": "b"})], [("read", {"path": "c"})], "done"])
    r = Loop(llm, tools=Toolbox(read), plugins=Plugins(Compact(max_chars=8000, keep_recent=1, head=100))).run("q")
    tools = [m["content"] for m in r.run.messages if m.get("role") == "tool"]
    assert "[compacted" in tools[0] and len(tools[0]) < 300 and tools[-1] == big


def test_node_retries_then_records_error():
    calls = {"n": 0}

    def flaky(s):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    g = Graph("r").node("flaky", flaky, retries=2).edge(START, "flaky")
    s = g.run({})
    assert s["ok"] and calls["n"] == 3 and not s["errors"]
    calls["n"] = -10
    s = Graph("r2").node("flaky", flaky, retries=1).edge(START, "flaky").run({})
    assert "after 2 attempts" in s["errors"]["flaky"]


def test_checkpoint_and_resume(tmp_path):
    seen = []

    def mk(name, fail=False):
        def fn(s):
            seen.append(name)
            if fail:
                raise RuntimeError("boom")
            return {name: True}
        return fn

    cp = tmp_path / "cp.json"
    g = Graph("c").node("a", mk("a")).node("b", mk("b", fail=True)).edge(START, "a").edge("a", "b")
    s1 = g.run({}, checkpoint=cp)
    assert s1["a"] and "boom" in s1["errors"]["b"] and cp.exists()
    g2 = Graph("c").node("a", mk("a")).node("b", mk("b")).edge(START, "a").edge("a", "b")  # b fixed
    s2 = g2.run({}, checkpoint=cp)
    assert s2["b"] and seen.count("a") == 1  # a was not re-run on resume


def test_structured_output_passes_schema(fake):
    llm = fake(['{"n": 3}'])
    r = Loop(llm, json_schema={"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}).run("q")
    assert r.json() == {"n": 3}
