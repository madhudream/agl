# Carebun Interactive (test copy)

A copy of the interactive book site's engine used to test what agl generates and to build the book
"AI Agent Loops and Graphs: Novice to Ninja" (`books/agents/`). The original site lives in its own repository.

- `python3 build.py --check` builds every `books/<slug>/` into `dist/` and validates it (balanced tags, meta
  comments, no dead links, house style).
- `python3 -m http.server 8000 -d dist` serves the result; open `/agents/`.
- `books/make/` is the engine's own guide and the template for a new book; `python3 engine/new_book.py <slug> "Title"` scaffolds one.
- `tools/smoke.mjs` opens every page in headless Chrome and exercises every interactive (it expects a free port; edit `PORT` if 8765 is taken).

Chapters are HTML fragments whose first line is a `<!--meta {...} -->` comment; interactives are `MB.widget(...)`
functions in the book's `assets/` folder. The agents book's chapter contract is written up in `skills/course-chapter.md`
at the repository root.
