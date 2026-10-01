# Porting agl into the real apps

Nothing in `~/apps/interactive` or `~/apps/bigIndianHub` was modified. This is the plan
for when the generated output has been reviewed.

## interactive (static Python book site)

The course builder writes a complete `books/<slug>/` folder into `apps/interactive-copy/`:
`book.json`, `chapters/NN-slug.html` (STYLE.md vocabulary, meta comment first line), and an empty
`assets/widgets-<slug>.js`. The copy's own `build.py --check` is the last node of the graph.

To port a generated book:

```bash
cp -r ~/apps/agentic-graph-loop/apps/interactive-copy/books/<slug> ~/apps/interactive/books/
cd ~/apps/interactive && python3 build.py --check && node tools/smoke.mjs
```

To generate on demand ("user asks for a course or uploads a PDF", `future.md` next phase), run
`agl serve --graphs examples/course_builder.py` next to the site and POST to `/graph` with
`{"name": "course-builder", "state": {"topic": "...", "source": "<pdf text>"}}`. The response carries
`book_dir` and `build_ok`; a small handler then copies the folder in and rebuilds. Three things the app
lacks today and this does not add: a backend process, data-driven quiz/flashcard widgets, per-user
progress (planned for hanudb). The chapter writer already emits `section.check` recall questions, so a
JSON-driven quiz widget is the natural next widget.

Review before porting, every time: `tools/REVIEW.md` in the app is a three-pass reviewer protocol (facts,
novice read, style). It is written as an agent prompt; it maps directly onto a `review` node with
`judge(llm, open("tools/REVIEW.md").read(), model=JUDGE_MODEL)`.

### Two things to port back into the engine itself

1. **Code highlighter bug (engine/assets/book.js).** The `colour()` pass holds comments and strings behind
   placeholders whose index is written in digits; the number pass then matches those digits and the
   restore step cannot find its placeholders, so every string and comment in every `language-python`
   block renders as a bare number. This affects the live memory and llm books too. The copy carries a
   two-line fix: the placeholder index is one private-use character (`U+E000 + i`) and the restore regex
   matches that. Diff `engine/assets/book.js` between the copy and the site.
2. **The agents book** (`books/agents/`): 16 chapters, 6 widgets (one renders the class whiteboard from
   its .excalidraw file). Copy the folder and rebuild; it passes `build.py --check`.

## bigIndianHub (Next.js, `modern/`)

The app already has one model API client (`modern/src/lib/ai.ts`, plain fetch, `purpose` labels, a cost
ledger) and a rule: one provider case in `lib/ai.ts`, never a second client. So do not import agl into
TypeScript. Two ways to use it:

1. **HTTP sidecar.** Run `agl serve` as a second Cloud Run service. From a `*.service.ts`, call
   `POST /graph` for multi-step work (research a business, draft and review a post, extract a flyer and
   verify it), keep single-shot calls in `lib/ai.ts`. Log the returned `usage.cost_usd` into the
   existing ledger under the same `purpose` key.
2. **Port the shape, not the code.** `graph.py` is 300 lines; a TypeScript port with `Promise.all` for
   waves is an afternoon. Do this only when a graph must run inside a request on Workers.

Keep the app's rules either way: no em dashes in any prompt or output (`plainDashes`), models chosen by
`ai:bench`, free tier off.

## Any new app

```python
from agl import LLM, Loop, Graph, Toolbox, tool, judge, check, default_plugins
from agl.memory import Memory
```

Start with one `Loop` and a deterministic `check`. Add a `judge` only for what you can not check. When
the order of steps is known, draw it in `Graph.from_text`. Add `Memory(user_id)` when the second
conversation should know about the first. Write `evals/tasks.jsonl` before you tune anything.
