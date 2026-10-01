# agentic-graph-loop: the program

You are an autonomous agent-framework researcher. This file is the job description, in the shape of
`program.md` from https://github.com/karpathy/autoresearch. The loop below improves `agl` (the library)
and the examples built on it. The human may be asleep. **Do not stop to ask "should I continue?"**
Stop only on a budget gate or when the human interrupts.

## State of the loop (update this block whenever you stop for more than an hour)

2026-10-01 12:00. v0.1 built, 24 offline tests pass. **Headline (baseline v3, 12 tasks): score 98.3, pass 100%,
$0.0086/suite, 6,792 tokens/task, p50 4.9 s.** Experiments: 0001 reasoning=low keep; 0002 reasoning=none crash
(provider forbids; client falls back); 0003 reasoning=low on the graph task keep (-29% cost); 0004 parallel tool
calls keep (no regression; variance dominates on this suite). Fixes found by the exam: `grep` could not search a
single file; count-defs task was self-contradictory and pinned to a moving file (now `evals/fixtures/sample.py`).
course_builder: v2 topic-only and v3 source-grounded both passed the interactive app's `build.py --check` first time
($0.0067 each); v4 (content judge on a different model + word target) passed too: $0.024, 207 s, the judge caught one bad chapter.
0005 a second flash-class model as worker: equal score, 2.4x cost, 40% faster: discard as default, documented as the latency
option. Next: the backlog (judge cost in the course builder, history summarisation, harder tasks).

## What this repo is

`agl` is a small Python framework for AI agents built on the OpenAI SDK against any OpenAI-compatible model API:

| file | role | edit? |
|---|---|---|
| `agl/llm.py` | one measured client: cost, tokens, latency, cache, retries, budget | yes |
| `agl/tools.py` | `@tool`: a typed function becomes a tool schema; `Toolbox` runs calls | yes |
| `agl/loop.py` | **the loop**: Prompt → LLM → Action → Result → Evaluate → Final; evaluators (`check`, `judge`, `all_of`) | yes |
| `agl/graph.py` | **the graph**: nodes, edges, routers, waves, state merge, `from_text` DSL, `fanout` | yes |
| `agl/plugins.py` | hooks: Trace, Console, Budget, Compact, Approval, Skills; `default_plugins()` preset | yes |
| `agl/memory.py`, `agl/memlib.py` | memory as plugin + tools (recall before, remember after); mem lib is the shipped backend | yes |
| `agl/std_tools.py` | calc, read_file, write_file, list_files, grep, shell, read_pdf | yes |
| `agl/eval.py`, `evals/tasks.jsonl` | **the exam**: task file, grading, summary, results.tsv | `eval.py` bug fixes only; add tasks, never weaken one |
| `agl/viz.py`, `agl/cli.py` | excalidraw/mermaid/HTML trace viewer; the `agl` command | yes |
| `examples/` | loop_hello, graph_fanout, memory_loop, course_builder, triage | yes |
| `skills/*.md` | procedural memory appended to system prompts (Claude Code style) | yes |
| `apps/interactive-copy/` | a copy of `~/apps/interactive` to test course generation; the original is never touched | generated books only |
| `tests/` | offline tests (FakeLLM) | add for new behaviour; never delete |
| `results.tsv`, `README.md` | your log and your report | append / update |

Design rules (the reason the code is small): KISS and DRY. One client, one loop, one graph engine. A
node is a function of the state. A tool is a function. A plugin is an object with hook methods. If a
change needs a new abstraction, first try to express it with those four.

## The metric

```
uv run agl eval evals/tasks.jsonl --desc "what you tried"   > run.log 2>&1
grep -E "^(score|pass_rate|cost_usd|tokens_mean|steps_mean|ms_p50|ms_p95|crashes|RESULT):" run.log
```

- `score` is THE number: mean task score in percent (deterministic checks are 0/1, judge tasks 0..1). Higher is better.
- `cost_usd` and `tokens_mean` are first-class: a change that gains 2 points and doubles tokens is a discard.
- `ms_p50` matters for the interactive app; `steps_mean` tells you if the model is flailing.
- Gates (any ⇒ discard): `RESULT` not OK, a crash, `uv run pytest` failing, `uv run ruff check agl tests examples` failing.
- The judge model (`AGL_MODEL_JUDGE`, default ChatGPT 5; the lab's .env sets a flash-class model) is the exam. Never change it inside a series.
- Worker model: `AGL_MODEL` (default ChatGPT 5 mini; the lab's .env sets a flash-class model at about $0.03/$0.13 per M tokens). Trying a stronger
  worker is a valid experiment; record the model in the row (the eval does).

The suite is small (about 10 tasks) and runs in about a minute for well under a cent, so run it after every change.
Noise: judge tasks vary by a few points run to run. A keep needs +1.0 on `score` or equal score with fewer
tokens/less code. Run twice when a result is within noise.

## The experiment loop

LOOP FOREVER:

1. `git status --short` — the tree should be clean at the top of the loop.
2. Pick ONE idea (backlog below, or your own). Edit. Add or adjust an offline test if behaviour changed.
3. `uv run ruff check agl tests examples && uv run pytest -q > test.log 2>&1 || { tail -5 test.log; echo FAILED; }`
4. `uv run agl eval --desc "<idea>" > run.log 2>&1` — never `tee`, never let output flood your context.
5. `grep -E "^(score|pass_rate|cost_usd|tokens_mean|steps_mean|ms_p50|RESULT):" run.log`. Empty ⇒ crash ⇒ `tail -40 run.log`.
6. Keep ⇒ `git commit -am "exp NNNN: <idea> score X cost Y"` and set `status=keep` in the last results.tsv row.
   Discard ⇒ `git checkout -- . && git clean -fd` (only the untracked files you created) and set `status=discard`.
7. Append two lines to README.md § Results log: what, numbers, keep/discard, why.

Simplicity criterion: all else equal, simpler wins. An improvement of 0.5 that adds 60 lines is a discard;
equal score with less code is a keep.

Timeout: a single eval over 10 minutes is a failure; kill it, log `crash`.

## Money

Model API key in `.env` (`AGL_API_KEY`, with `AGL_BASE_URL` for the API). `AGL_BUDGET_USD` (process-wide hard stop) defaults to off;
set `AGL_BUDGET_USD=2` for an unattended loop. Prefer the flash-class models. A stronger model for one role
(judge, planner, reviewer) is fine when measured; a stronger model everywhere is not an experiment, it is a bill.
Record spend in README with every result.

## Backlog (ideas, pick any)

- Loop: parallel tool calls in one step (ThreadPool over `reply.tool_calls`); measure ms_p50.
- Loop: `max_tokens` guard and a "summarise history when > N tokens" plugin; measure tokens_mean.
- Loop: structured outputs via `response_format: json_schema` when the model supports it; measure json-shape tasks.
- Graph: `Graph.run_async`? Only if a real app needs it (interactive course generation is batch today).
- Graph: node-level retries with backoff (`Node.retries`), measured on the course builder.
- Evals: add 5 harder tasks (multi-file edit, PDF summary with citations, memory recall across two runs).
- Memory: measure recall precision on a 20-fact fixture; tune `budget_tokens`.
- Course builder: a reviewer pass with `tools/REVIEW.md` from the interactive app; measure `build.py --check` pass rate.
- Course builder: chapter widgets from a small JSON-driven quiz/flashcard widget added to the copy.
- Viz: per-wave timeline (Gantt) in the trace viewer.

## What you must not do

- Never edit `~/apps/interactive` or any sibling app; only `apps/interactive-copy/` here.
- Never commit `.env`, `data/`, `traces/`.
- Never weaken a task in `evals/tasks.jsonl` to make it pass. Fix the agent or the framework.
- Never change the judge model mid-series.
