# Graph engineering for AI agents, in one sitting

This is the student guide for `agl`. It follows the whiteboard in
`loop-engineering-and-graph-engineering.excalidraw` and the code in `agl/`. Read it next to the code: every
idea here is under 300 lines of Python.

## 1. Two kinds of tasks

Before any agent, ask: **can I measure the result?**

| measurable | non-measurable |
|---|---|
| reduce page load time | implement dark mode |
| lower validation loss | integrate a payment gateway |
| pass more eval tasks | "make the docs nicer" |

What gets measured gets improved. A measurable task can run inside a loop that keeps what helps and
discards what does not (that is `CLAUDE.md` in this repo, copied from karpathy/autoresearch). A
non-measurable task needs a human or a judge to say "pass" or "fail", so we build the judge first.

Measurable tasks split again: **open-ended** (let the model decide what to try) and **closed** (we tell it
what to try). The eval suite in `evals/tasks.jsonl` is closed; the experiment loop in `CLAUDE.md` is open.

## 2. The loop

```
Prompt ──► LLM ──► Action ──► Result ──┐
           ▲                           │
           │                           ▼
           └──── Fail ◄── Evaluate ──► Pass ──► Final Answer
```

A chatbot answers once. An agent **loops**: the model sees the task and the tools, calls a tool
(Action), sees what came back (Result), and tries again until it has an answer. Then something
**evaluates** the answer. Pass means we are done. Fail goes back into the loop as feedback.

`agl/loop.py` is this picture. The evaluator is a plain function. Use a deterministic one when you can
(`check(lambda a: a.isdigit())`), an LLM judge when you must (`judge(llm, "the answer cites a file")`).
Cheap checks first, judge last: `all_of(check(...), judge(...))`.

Peter Steinberger's line: you should not be prompting coding agents anymore, you should be designing
loops that prompt your agents. The loop is the unit of design, not the prompt.

## 3. The graph

```
Prompt ──► Agent ──┬──► Loop A ──┐
                   ├──► Loop B ──┼──► Review ──► Final
                   └──► Loop C ──┘
```

Sean Chen (AI Stories, Waku Agent): **a loop discovers what to do next; a graph pre-determines what
happens next.** When we already know the order, we should not make the model rediscover it on every run.
A graph is a map of steps. Each node does one job. Each edge says "when this finishes, go there".

`agl/graph.py` runs a graph in **waves**: every node whose inputs have all arrived runs in the same wave,
in parallel, and writes its own keys into a shared state. Parallel nodes must write disjoint keys; two
nodes writing the same key in one wave is a bug, and the engine says so.

You draw the graph as text, and the text is the code:

```python
g = Graph.from_text("""
    START -> plan
    plan -> write_a, write_b, write_c      # fan-out: one wave, three parallel loops
    write_a, write_b, write_c -> edit      # fan-in: edit waits for all three
    edit -> review
    review ?pass-> END                     # router: a function of the state picks the label
    review ?fail-> edit                    # back edge: re-trigger edit with feedback
""", nodes={...}, routers={"review": lambda s: "pass" if s["ok"] else "fail"})
```

`agl draw` turns that into Mermaid or an `.excalidraw` file. `agl viz` replays a run.

### The patterns you will reuse

| pattern | shape | where in this repo |
|---|---|---|
| sequence | a → b → c | course_builder: outline → write → assemble |
| fan-out / fan-in | a → b,c,d → e | graph_fanout: plan → write_a,b,c → edit |
| map (width known at run time) | `fanout(fn, over="chapters", into="drafts")` | course_builder: one writer per chapter |
| router | `a ?label-> b` | review ?pass-> END |
| review cycle | review ?fail-> edit, edit → review | graph_fanout, course_builder |
| sub-graph as node | `g.node("sub", other_graph)` | tests |
| loop as node | `loop.as_node("write about {topic}")` | everywhere |

### A lesson from the first live run

The first version of `graph_fanout` had no `edit` node: three writers fanned out and a reviewer judged the
three paragraphs glued together. The reviewer failed three times in a row with "not one coherent article".
Of course: three writers who never see each other can not produce one article. No prompt fixes that. The
graph shape does: add an editor node between the fan-in and the review. Second lesson from the same run:
the rubric said "one concrete example" and the judge failed an article for having two. Rubrics are code;
test them.

## 4. Memory

`agl/memory.py` adds memory through a small backend interface; mem lib is the shipped one. Before a run, the task is searched and a dated fact block is added to the
system prompt. After a pass, the task and the answer are handed to the backend, which extracts facts, dedups
them, and keeps the old version of a changed fact with its validity window. The model can also call
`recall()` and `remember()` as tools. Memory is one SQLite file you can open.

## 5. Plugins, skills, evals

Everything around the loop is a plugin with hook methods (`on_llm_response`, `on_tool_result`,
`on_node_end`, ...). Trace writes JSONL, Console prints, Budget stops a runaway run, Skills appends
`skills/*.md` to the system prompt (procedural memory: edit a markdown file, the agent behaves
differently). Everything is a plugin, in forty lines.

`agl eval` runs `evals/tasks.jsonl`, grades each answer (deterministic checks, then a judge on a different
model), and prints one grep-able summary. `results.tsv` is the lab notebook. `CLAUDE.md` is the lab
protocol: change one thing, run the exam, keep or discard.

## 6. Exercises

1. Draw your own task as a graph in `Graph.from_text`. Which nodes can share a wave?
2. Replace the judge in `graph_fanout` with a deterministic check. What can you check without an LLM?
3. Add a `summarise` node that runs in parallel with `edit` and writes a different key. Then try writing
   the same key and read the error.
4. Run `examples/memory_loop.py` twice. Open `data/memory.sqlite` and find your facts.
5. Pick one backlog item in `CLAUDE.md`, run the loop for one iteration, and append to `results.tsv`.
