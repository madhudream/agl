"""Example 4: the interactive-app port. A topic (or a PDF) becomes a book folder.

    topic/pdf ──► outline ──► write (fan-out, one loop per chapter) ──► assemble ──► build_check ──► END
                                                                            ▲             │ fail
                                                                            └──── fix ◄───┘

Each chapter is written by its own loop whose evaluator is the deterministic
`validate_chapter` (the same rules `build.py --check` and STYLE.md enforce), so a
chapter that breaks a rule is sent back with the exact complaint before it is
ever written to disk. `build_check` runs the real `build.py --check` of the copied
app; a failure routes to `fix`, which repairs only the chapters named in the errors.

    uv run python examples/course_builder.py "Graph engineering for AI agents" --chapters 3
    uv run python examples/course_builder.py --pdf notes.pdf --chapters 4
    (cd apps/interactive-copy && ./deploy.sh --preview)   # then open http://localhost:8000/<slug>/
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from agl import (
    JUDGE_MODEL,
    LLM,
    Graph,
    Loop,
    Plugins,
    Skills,
    all_of,
    check,
    default_plugins,
    fanout,
    judge,
    parse_json,
)
from agl.env import ROOT
from agl.std_tools import read_pdf

APP = ROOT / "apps" / "interactive-copy"
CONTENT_RUBRIC = ("Every claim agrees with the source material given in the task (when there is one) and with the "
                  "chapter's own summary; definitions are not inverted; numbers are derived in a calc block or "
                  "labelled; the running analogy is used; nothing is invented. Judge content, not HTML.")
REQUIRED = {"lede": r'<p class="lede">', "analogy": r'<aside class="note analogy">', "try": r'<section class="try">',
            "faq": r'<section class="faq">', "carry": r'<section class="carry">', "check": r'<section class="check">'}


def validate_chapter(html: str, expect: dict | None = None) -> bool | str:
    """The chapter contract. Returns True or a precise complaint the writer can act on.

    `expect` may pin meta fields ({"title": ..., "part": ...}) so every chapter uses the plan's labels.
    """
    problems = []
    first = html.strip().splitlines()[0] if html.strip() else ""
    m = re.match(r"<!--meta\s+(\{.*\})\s*-->", first)
    if not m:
        problems.append("first line must be the <!--meta {...} --> comment")
    else:
        try:
            meta = json.loads(m.group(1))
            for k in ("title", "part", "minutes", "summary"):
                if not meta.get(k):
                    problems.append(f"meta is missing {k}")
            for k, v in (expect or {}).items():
                if meta.get(k) != v:
                    problems.append(f'meta {k} must be exactly "{v}"')
        except json.JSONDecodeError:
            problems.append("meta comment is not valid JSON")
    if "—" in html:
        problems.append("contains an em dash (use a comma or a full stop)")
    if "!" in re.sub(r"<[^>]+>|<!--.*?-->", "", html).replace("!=", ""):
        problems.append("contains an exclamation mark")
    if re.search(r"<h1\b", html):
        problems.append("contains an <h1> (the engine adds the title)")
    if "data-widget" in html:
        problems.append("contains a data-widget (no widgets exist for this book yet)")
    if re.search(r"<(html|head|body)\b", html):
        problems.append("must be an HTML fragment: no html/head/body")
    for tag in ("pre", "details", "section", "aside", "table", "div", "ol", "ul", "p", "h2"):
        a, b = len(re.findall(rf"<{tag}\b", html)), len(re.findall(rf"</{tag}>", html))
        if a != b:
            problems.append(f"<{tag}> opened {a} times, closed {b}")
    for name, pat in REQUIRED.items():
        if not re.search(pat, html):
            problems.append(f"missing the {name} component ({pat})")
    words = len(re.sub(r"<[^>]+>", " ", html).split())
    if not 1100 <= words <= 2700:
        problems.append(f"{words} words; the chapter must be 1,400 to 2,400 words")
    if (n := len(re.findall(r'<section class="faq">.*?</section>', html, re.S) and re.findall(r"<details>", html))) < 5:
        problems.append(f"only {n} <details> blocks; the FAQ needs 4 to 7 questions and Check yourself 2 to 3 answers")
    return True if not problems else "Fix these and resend the whole chapter: " + "; ".join(problems)


def build(llm: LLM, *, chapters: int = 3) -> Graph:
    skills = Plugins(Skills(only=["plain-writing", "course-chapter"]))

    def outline_ok(answer: str) -> bool | str:
        try:
            plan = parse_json(answer)
        except ValueError as exc:
            return f"not valid JSON: {exc}"
        n = len(plan.get("chapters", []))
        return True if n == chapters else f"the plan has {n} chapters; it must have exactly {chapters}"

    outliner = Loop(llm, name="outline", json_mode=True, evaluate=check(outline_ok), max_fails=2,
                    system="You design short interactive books for students. Reply with JSON only.")

    def outline(s: dict) -> dict:
        source = f"\n\nSource material (use only this for facts):\n{s['source'][:30000]}" if s.get("source") else ""
        prompt = (
            f"Topic: {s['topic']}\nDesign a book of exactly {chapters} chapters. "
            "One running analogy for the whole book.\n"
            'JSON: {"slug": "lowercase-dashes", "title": "Title: Subtitle", "short": "two words", '
            '"subtitle": "one sentence", '
            '"analogy": "the running analogy", "level": "no background needed", "parts": {"Part I": "blurb"}, '
            '"chapters": [{"n": 1, "slug": "lowercase-dashes", "title": "...", "part": "Part I", "minutes": 8, '
            '"summary": "one sentence", "goals": ["...", "..."], "facts": ["key facts or formulas to include"]}]}'
            f"{source}")
        plan = parse_json(outliner.run(prompt, state=s).answer)
        plan["slug"] = re.sub(r"[^a-z0-9-]", "-", plan["slug"].lower())[:30].strip("-") or "book"
        plan["chapters"] = plan["chapters"][:chapters]
        parts = list(plan.get("parts") or {"Part I": ""})
        for i, ch in enumerate(plan["chapters"], 1):  # the plan's labels are the law: no "(Part I)" drift
            ch["n"] = i
            ch["part"] = ch["part"] if ch.get("part") in parts else parts[0]
            ch["slug"] = re.sub(r"[^a-z0-9-]", "-", str(ch.get("slug") or ch["title"]).lower())[:40].strip("-")
        return {"plan": plan}

    def write_one(ch: dict, s: dict) -> dict:
        p = s["plan"]
        pinned = {"title": ch["title"], "part": ch["part"]}
        # cheap deterministic contract first; the content judge (a different model) only sees chapters that pass it
        content = judge(llm, CONTENT_RUBRIC, threshold=0.7, model=JUDGE_MODEL)
        writer = Loop(llm, name="write", plugins=skills, max_fails=3,
                      evaluate=all_of(check(lambda html: validate_chapter(html, pinned)), content),
                      system="You write one chapter of an interactive book as an HTML fragment. Output the HTML only.")
        source = f"\n\nSource material (facts must come from here):\n{s['source'][:20000]}" if s.get("source") else ""
        task = (f"Book: {p['title']}\nRunning analogy: {p['analogy']}\n"
                f"Chapter {ch['n']}: {ch['title']}\nmeta.title must be exactly: {ch['title']}\n"
                f"meta.part must be exactly: {ch['part']}\n"
                f"Summary: {ch['summary']}\nGoals: {'; '.join(ch.get('goals', []))}\nMust include: "
                f"{'; '.join(ch.get('facts', []))}\nMinutes: {ch['minutes']}\n"
                f"Length: aim for 1,800 words and stop by 2,200 (hard limit 2,400; first drafts tend to run long)."
                f"{source}")
        r = writer.run(task, state=s)
        return {**ch, "html": r.answer, "ok": r.passed, "verdict": (r.verdict or {}).get("feedback", "")}

    def assemble(s: dict) -> dict:
        p = s["plan"]
        root = APP / "books" / p["slug"]
        (root / "chapters").mkdir(parents=True, exist_ok=True)
        (root / "assets").mkdir(exist_ok=True)
        for old in (root / "chapters").glob("*.html"):
            old.unlink()
        for ch in s["chapters"]:
            (root / "chapters" / f"{ch['n']:02d}-{ch['slug']}.html").write_text(ch["html"].strip() + "\n")
        script = f"widgets-{p['slug']}.js"
        (root / "assets" / script).write_text('(function () { "use strict"; /* no interactives yet */ })();\n')
        (root / "book.json").write_text(json.dumps({
            "slug": p["slug"], "title": p["title"], "short": p.get("short", p["title"].split(":")[0]),
            "eyebrow": "Generated by agl", "order": 50, "hue": 150, "hidden": False, "subtitle": p.get("subtitle", ""),
            "level": p.get("level", "no background needed"), "scripts": [script],
            "how": ["<b>In order.</b> Each chapter uses only what the earlier ones taught."],
            "parts": p.get("parts", {"Part I": ""}), "credits": "Drafted by an agl graph; reviewed by its evaluators."},
            indent=2) + "\n")
        return {"book_dir": str(root)}

    def build_check(s: dict) -> dict:
        r = subprocess.run([sys.executable, "build.py", "--check"], cwd=APP, capture_output=True, text=True,
                           timeout=120)
        out = r.stdout + r.stderr
        slug = s["plan"]["slug"]
        errs = [line.strip(" !") for line in out.splitlines() if line.strip().startswith("!") and f"{slug}/" in line]
        return {"build_ok": r.returncode == 0 and not errs, "build_errors": errs, "build_log": out[-1500:]}

    fixer = Loop(llm, name="fix", plugins=skills, evaluate=check(validate_chapter), max_fails=2,
                 system="You repair one chapter of an interactive book (HTML fragment). "
                        "Output the full fixed HTML only.")

    def fix(s: dict) -> dict:
        chapters = []
        for ch in s["chapters"]:
            mine = [e for e in s["build_errors"] if f"{ch['n']:02d}-{ch['slug']}" in e]
            if mine:
                problems = "\n- ".join(mine)
                r = fixer.run(f"Problems reported by the build:\n- {problems}\n\nChapter:\n{ch['html']}", state=s)
                ch = {**ch, "html": r.answer, "ok": r.passed}
            chapters.append(ch)
        return {"chapters": chapters}

    g = Graph.from_text("""
        START -> outline
        outline -> write
        write -> assemble
        assemble -> build_check
        build_check ?ok-> END
        build_check ?fail-> fix
        fix -> assemble
    """, nodes={"outline": outline, "write": fanout(write_one, over="plan_chapters", into="chapters", workers=6),
                "assemble": assemble, "build_check": build_check, "fix": fix},
         routers={"build_check": lambda s: "ok" if s["build_ok"] else "fail"}, name="course-builder")
    # fanout reads a top-level list: expose plan["chapters"] under its own key after outline
    g.nodes["outline"].fn = _with(outline, lambda out: {**out, "plan_chapters": out["plan"]["chapters"]})
    g.nodes["fix"].max_visits = 2
    return g


def _with(fn, post):
    def node(s):
        return post(fn(s))
    node.__name__ = fn.__name__
    return node


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", nargs="*")
    ap.add_argument("--pdf", help="ground the book in a PDF (facts must come from it)")
    ap.add_argument("--source", help="ground the book in a text/markdown file")
    ap.add_argument("--chapters", type=int, default=3)
    ap.add_argument("--model")
    a = ap.parse_args()
    state = {"topic": " ".join(a.topic) or (Path(a.pdf).stem if a.pdf else "Graph engineering for AI agents")}
    if a.pdf:
        state["source"] = read_pdf(path=a.pdf)
    elif a.source:
        state["source"] = Path(a.source).read_text()
    llm = LLM(a.model) if a.model else LLM()
    out = build(llm, chapters=a.chapters).run(state, plugins=default_plugins(verbose=False))
    print(json.dumps({"book": out.get("book_dir"), "build_ok": out.get("build_ok"), "errors": out["errors"],
                      "build_errors": out.get("build_errors"), "path": out["_path"],
                      "chapters_ok": [c["ok"] for c in out.get("chapters", [])], "ms": out["_ms"]}, indent=1))
