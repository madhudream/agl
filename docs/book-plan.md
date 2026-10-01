# Book plan: AI Agent Loops and Graphs, Novice to Ninja (edition 2)

## Intent

A textbook for people who have used agents and want to build them: loops first, then graphs, then real
problems. It teaches what a loop is and how to implement it, what a graph is and when to reach for one,
the problems every builder hits and how to solve them, and a set of worked examples shaped so the reader
can swap in their own problem. agl is the companion code; every idea maps to a file in it.

Not in the book: how agl itself was developed, experiment numbers, results.tsv, keep/discard verdicts,
"from the lab" asides about our process. Those live in the repository README for maintainers.

Memory is taught as "a memory framework (mem0 is a well-known one)". agl ships a backend built on our
own framework; the book shows the interface and says you can plug in another.

## Running analogy and character

The newsroom: reporter (loop), desk (graph), editor (evaluator), archive (memory), style guide (skills),
the printer's proof (the build check). Priya, who builds a course app, remains the running character.
The whiteboard widget stays in chapter 1 as the map of the book.

## Chapters

Part I · Foundations (Novice)
1. From chatbots to agents: tools, a loop, an evaluator, a place to work; the ladder; the whiteboard.
2. Which problems suit a loop: measurable vs non-measurable, open vs closed, judge-first for the rest.
3. Anatomy of a loop: the seven boxes, two cycles, the ways a loop ends. Step-through widget.

Part II · Building loops (Apprentice)
4. Your first loop: install agl, one client, one loop, one tool, one check; reading a trace.
5. Tools: functions become tools; errors as text; confinement; designing tools that steer.
6. Evaluators: check, judge, all_of; writing feedback for the model; rubrics are code; judge is not worker.
7. Models, tokens and cost: the prompt grows; roles (worker, judge, specialist); reasoning effort; budgets.
8. Loop problems and fixes: runaway, flailing, tool errors, context bloat, format drift, invented facts,
   prompt injection through tool output, non-determinism. Symptom, cause, fix, code.

Part III · Building graphs (Journeyman)
9. Why graphs: a loop discovers, a graph pre-determines; the pattern catalogue (sequence, fan-out/fan-in,
   map, router, review cycle, repair path, sub-graph, loop as node). Pattern picker widget.
10. The engine: nodes, state, waves, disjoint keys, routers, max_visits. Wave scheduler widget.
11. Drawing and designing a graph: the text DSL, back edges, fanout, sub-graphs, export; design from the
    output contract backwards.
12. Graph problems and fixes: three writers and no editor; a literal judge; a graph that stalls; a cycle
    that never ends; two nodes writing one key; a node that dies; judges that cost more than workers.

Part IV · Around the loop (Ninja)
13. Plugins, tracing, skills: hooks; what to log; budgets; skills as procedural memory; the trace viewer.
14. Memory: a memory framework in a loop; recall before, remember after; tools; scoping by user; what
    not to store; testing memory separately.
15. Evals and the improvement loop: write an exam for your agent; grade cheap first; a results log; the
    autoresearch pattern as a technique for your own project.

Part V · Real world (Practice)
16. Case study: a course from a topic or a PDF; the output contract; one loop per chapter; the real build
    check as the last node; grounding; a content judge.
17. Five problems, five graphs: research assistant, support triage, code-review bot, document extraction
    pipeline, weekly report writer. Each: shape in the DSL, what to evaluate, where memory goes, what
    breaks first.
18. Shipping: serving over HTTP, safety and budgets, review before publish, the exercises, the whiteboard
    cold.

Widgets: whiteboard (ch 1), task-sorter (ch 2), loop-sim (ch 3), cost-calculator (ch 7), pattern-picker
(ch 9, new), wave-scheduler (ch 10). The results chart goes.

## Code changes that the book needs

- `agl/memory.py`: a `MemoryBackend` protocol with one shipped backend; the book shows the protocol.
- `examples/triage.py`: a router-first graph (classify, handle, policy check) as the second runnable
  template next to the course builder.
- Everything else already exists.
