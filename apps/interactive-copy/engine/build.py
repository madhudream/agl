#!/usr/bin/env python3
"""Carebun Interactive: a shelf of interactive books, built into one static site (stdlib only).

    python3 engine/build.py            build every book in books/ into dist/
    python3 engine/build.py --check    also fail on bad meta, unknown widgets, dead links, unbalanced tags

A book is a folder: books/<slug>/book.json + chapters/NN-slug.html (HTML fragments) + assets/ (its own
widgets and data). The engine supplies the shell, the stylesheet and the widget runtime. See AUTHORING.md.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE, BOOKS, DIST = ROOT / "engine", ROOT / "books", ROOT / "dist"
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
META = re.compile(r"^\s*<!--meta\s+(\{.*?\})\s*-->", re.S)
PROTECTED = re.compile(r"(<pre\b.*?</pre>|<code\b.*?</code>|<[^>]+>)", re.S)
ENGINE_JS = ["book.js", "widgets-core.js"]
FONTS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800"
         "&family=Figtree:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600"
         "&family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,600;1,7..72,400&display=swap")


def strip(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def esc(s: str) -> str:
    return html.escape(strip(s), quote=True)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", strip(s).lower()).strip("-")[:60]


def version(*dirs: Path) -> str:
    return str(int(max((p.stat().st_mtime for d in dirs if d.exists() for p in d.iterdir() if p.is_file()), default=0)))


class Book:
    def __init__(self, folder: Path):
        self.dir = folder
        self.cfg = json.loads((folder / "book.json").read_text(encoding="utf-8"))
        self.slug = self.cfg.get("slug", folder.name)
        self.title = self.cfg["title"]
        self.scripts = self.cfg.get("scripts", [])
        self.replace = self.cfg.get("replace", {})           # {"word in sources": "word shown in prose"}
        self.v = version(ENGINE / "assets", folder / "assets")
        self.chapters = self.load()

    def prose(self, text: str) -> str:
        """Apply the book's word replacements to prose only; code, <pre> and tags stay untouched."""
        if not self.replace:
            return text
        parts = PROTECTED.split(text)
        for i in range(0, len(parts), 2):
            for a, b in self.replace.items():
                parts[i] = re.sub(rf"\b{re.escape(a)}\b(?!{re.escape(b[len(a):]) if b.startswith(a) and len(b) > len(a) else '$^'})", b, parts[i])
        return "".join(parts)

    def load(self) -> list[dict]:
        out = []
        for p in sorted((self.dir / "chapters").glob("[0-9][0-9]-*.html")):
            raw = p.read_text(encoding="utf-8")
            m = META.match(raw)
            if not m:
                raise SystemExit(f"{self.slug}/{p.name}: first line must be <!--meta {{...}} -->")
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{self.slug}/{p.name}: meta is not valid JSON: {e}") from e
            body = self.prose(raw[m.end():].strip())
            body = re.sub(r'href="/(\d\d-[^"]*)"', rf'href="/{self.slug}/\1"', body)     # chapter links are book-relative
            heads, seen = [], set()

            def add_id(mm, heads=heads, seen=seen):
                hid = slugify(mm.group(2)) or "s"
                while hid in seen:
                    hid += "-x"
                seen.add(hid)
                heads.append((hid, strip(mm.group(2))))
                return f'<h2 id="{hid}"{mm.group(1)}>{mm.group(2)}</h2>'
            body = re.sub(r"<h2([^>]*)>(.*?)</h2>", add_id, body, flags=re.S)
            words = len(strip(body).split())
            out.append({"file": p.name, "slug": p.stem, "n": int(p.stem[:2]), "body": body, "heads": heads, "words": words,
                        "title": self.prose(meta["title"]), "part": meta.get("part", ""),
                        "summary": self.prose(meta.get("summary", "")),
                        "minutes": meta.get("minutes") or max(3, round(words / 200)),
                        "widgets": re.findall(r'data-widget="([\w-]+)"', body)})
        return out

    @property
    def minutes(self) -> int:
        return sum(c["minutes"] for c in self.chapters)

    @property
    def n_widgets(self) -> int:
        return sum(len(c["widgets"]) for c in self.chapters)

    def url(self, c: dict | None = None) -> str:
        return f"/{self.slug}/" + (f"{c['slug']}/" if c else "")


def theme_style(cfg: dict) -> str:
    """A book may set its own accent: {"accent": {"light": [accent, ink, soft], "dark": [accent, ink, soft]}}."""
    a = cfg.get("accent")
    if not a:
        return ""
    lt, dk = a["light"], a["dark"]
    dark = f"--accent:{dk[0]};--accent-ink:{dk[1]};--accent-soft:{dk[2]};"
    return (f"<style>:root{{--accent:{lt[0]};--accent-ink:{lt[1]};--accent-soft:{lt[2]};}}"
            f"@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{{dark}}}}}"
            f":root[data-theme=dark]{{{dark}}}</style>")


def shell(title: str, desc: str, main: str, *, cls: str, book: Book | None = None, current: str | None = None) -> str:
    v = book.v if book else version(ENGINE / "assets")
    js = [f"/assets/{a}" for a in ENGINE_JS] + ([f"/{book.slug}/assets/{a}" for a in book.scripts] if book else [])
    # data and widget files register on window.MB, which widgets-core creates; core must load before them
    scripts = "\n".join(f'<script defer src="{s}?v={v}"></script>' for s in js)
    side, links, crumb = "", "", ""
    if book:
        side = (f'<nav class="sidebar" id="sidebar" aria-label="Contents">'
                f'<a class="side-home" href="/">&larr; All books</a>'
                f'<a class="side-book" href="{book.url()}">{book.title}</a>'
                f'<div class="side-meter"><span id="done-count">0</span> of {len(book.chapters)} chapters read'
                f'<div class="meter"><i id="done-bar"></i></div></div>{nav(book, current)}</nav>')
        links = "".join(f'<a class="top-link" href="/{book.slug}/{l["chapter"]}/">{html.escape(l["label"])}</a>'
                        for l in book.cfg.get("links", []))
        crumb = f'<span class="crumb-sep">/</span><a class="crumb" href="{book.url()}">{html.escape(book.cfg.get("short", book.title))}</a>'
    toggle = ('<button class="icon-btn" id="nav-toggle" aria-label="Contents" aria-expanded="false" aria-controls="sidebar">'
              '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h10" '
              'stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg></button>') if book else ""
    credits = book.cfg.get("credits", "") if book else SITE.get("credits", "")
    foot_name = (book.cfg.get("brand", {}).get("name") or book.title) if book else SITE["name"]
    foot_tag = (book.cfg.get("brand", {}).get("tagline") or "") if book else SITE["tagline"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta name="theme-color" content="#f7f3ea">
<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">
<script>(function(){{try{{var t=localStorage.getItem("mb-theme");if(t)document.documentElement.dataset.theme=t}}catch(e){{}}}})()</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="/assets/book.css?v={v}">
{theme_style(book.cfg) if book else ""}
</head>
<body class="{cls}" data-book="{book.slug if book else ''}">
<a class="skip" href="#main">Skip to the text</a>
<div class="progress" aria-hidden="true"><i></i></div>
<header class="top">
  {toggle}
  <a class="brand" href="/"><span class="brand-mark" aria-hidden="true"></span><span class="brand-t">{html.escape(SITE["name"])}</span></a>{crumb}
  <span class="top-gap"></span>
  {links}
  <button class="icon-btn" id="theme-toggle" aria-label="Switch theme">
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z" fill="currentColor"/></svg>
  </button>
</header>
<div class="shell{'' if book else ' no-side'}">
{side}
<main id="main">
{main}
</main>
</div>
<footer class="foot">
  <p><strong>{html.escape(foot_name)}</strong>{' · ' + html.escape(foot_tag) if foot_tag else ''}</p>
  <p>{credits}</p>
</footer>
{scripts}
</body>
</html>
"""


def nav(book: Book, current: str | None) -> str:
    rows, part = [], None
    for c in book.chapters:
        if c["part"] != part:
            if part is not None:
                rows.append("</ol>")
            part = c["part"]
            rows.append(f'<p class="nav-part">{html.escape(part)}</p><ol>')
        cur = ' aria-current="page"' if c["slug"] == current else ""
        lab = ' <span class="nav-lab" title="interactive">&#9670;</span>' if c["widgets"] else ""
        rows.append(f'<li><a href="{book.url(c)}" data-slug="{c["slug"]}"{cur}><span class="nav-n">{c["n"]:02d}</span>'
                    f'<span class="nav-t">{c["title"]}{lab}</span></a></li>')
    rows.append("</ol>")
    return "\n".join(rows)


def chapter_page(book: Book, c: dict) -> str:
    cs = book.chapters
    i = cs.index(c)
    prev_c, next_c = (cs[i - 1] if i else None), (cs[i + 1] if i + 1 < len(cs) else None)
    toc = "".join(f'<li><a href="#{h}">{t}</a></li>' for h, t in c["heads"])
    pn = '<nav class="prevnext" aria-label="Chapters">'
    pn += (f'<a class="pn prev" href="{book.url(prev_c)}"><small>Previous</small><b>{prev_c["title"]}</b></a>'
           if prev_c else "<span></span>")
    pn += (f'<a class="pn next" href="{book.url(next_c)}"><small>Next</small><b>{next_c["title"]}</b>'
           f'<em>{next_c["summary"]}</em></a>' if next_c else
           '<a class="pn next" href="/"><small>You finished the book</small><b>Back to the shelf</b></a>')
    pn += "</nav>"
    main = f"""<article class="chapter" data-slug="{c['slug']}">
<header class="ch-head">
  <p class="ch-part">{html.escape(c['part'])}</p>
  <p class="ch-num">Chapter {c['n']}</p>
  <h1>{c['title']}</h1>
  <p class="ch-sum">{c['summary']}</p>
  <p class="ch-meta">{c['minutes']} min read{' · interactive' if c['widgets'] else ''}</p>
</header>
{f'<details class="onpage"><summary>On this page</summary><ol>{toc}</ol></details>' if toc else ''}
<div class="prose">
{c['body']}
</div>
<div class="done-row"><button class="done-btn" id="mark-done" data-slug="{c['slug']}">Mark this chapter as read</button></div>
{pn}
</article>"""
    return shell(f"{strip(c['title'])} · {strip(book.title)}", c["summary"], main, cls="is-chapter", book=book, current=c["slug"])


def cover(book: Book) -> str:
    cfg, parts = book.cfg, {}
    for c in book.chapters:
        parts.setdefault(c["part"], []).append(c)
    sections = []
    for part, cs in parts.items():
        cards = "".join(
            f'<a class="toc-card" href="{book.url(c)}" data-slug="{c["slug"]}"><span class="toc-n">{c["n"]:02d}</span>'
            f'<span class="toc-b"><b>{c["title"]}</b><em>{c["summary"]}</em>'
            f'<small>{c["minutes"]} min{" · interactive" if c["widgets"] else ""}</small></span></a>' for c in cs)
        blurb = cfg.get("parts", {}).get(part, "")
        sections.append(f'<section class="toc-part"><h2>{html.escape(part)}</h2>'
                        f'{f"<p class=toc-blurb>{html.escape(blurb)}</p>" if blurb else ""}<div class="toc-grid">{cards}</div></section>')
    t = cfg["title"].split(":", 1)
    h1 = f"{html.escape(t[0])}<br><span>{html.escape(t[1].strip())}</span>" if len(t) == 2 else html.escape(cfg["title"])
    cta = f'<a class="btn primary" href="{book.url(book.chapters[0])}" id="start-btn">Start reading</a>' if book.chapters else ""
    for l in cfg.get("links", [])[:1]:
        cta += f'<a class="btn" href="/{book.slug}/{l["chapter"]}/">Open the {html.escape(l["label"].lower())}</a>'
    pitch, b = "", cfg.get("brand")
    if b:
        widgets = "".join(f'<div class="widget" data-widget="{w}"></div>' for w in b.get("widgets", []))
        pitch = (f'<section class="pitch"><p class="eyebrow">{html.escape(b.get("eyebrow", ""))}</p><h2>{html.escape(b["name"])}</h2>'
                 f'<p class="tagline">{html.escape(b.get("tagline", ""))}</p><p>{b.get("pitch", "")}</p>{widgets}'
                 f'{f"<p class=fine>{b["fine"]}</p>" if b.get("fine") else ""}</section>')
    how = "".join(f"<li>{x}</li>" for x in cfg.get("how", []))
    main = f"""<div class="cover">
<section class="hero">
  <p class="eyebrow">{html.escape(cfg.get("eyebrow", "An interactive book"))}</p>
  <h1>{h1}</h1>
  <p class="hero-sub">{cfg.get("subtitle", "")}</p>
  <p class="hero-cta">{cta}</p>
  <p class="hero-facts">{len(book.chapters)} chapters · about {round(book.minutes / 60, 1)} hours · {book.n_widgets} interactives · {html.escape(cfg.get("level", "no background needed"))}</p>
</section>
{pitch}
{f'<section class="how"><h2>How to read this book</h2><ol>{how}</ol></section>' if how else ''}
{''.join(sections)}
</div>"""
    return shell(f"{cfg['title']} · {SITE['name']}", cfg.get("description", cfg.get("subtitle", "")), main, cls="is-cover", book=book)


def home(books: list[Book]) -> str:
    cards = []
    for b in books:
        c = b.cfg
        cards.append(
            f'<a class="shelf-card" href="{b.url()}" style="--hue:{c.get("hue", 24)}">'
            f'<span class="shelf-spine" aria-hidden="true"></span><span class="shelf-b">'
            f'<small>{html.escape(c.get("eyebrow", "An interactive book"))}</small><b>{html.escape(c["title"])}</b>'
            f'<em>{strip(c.get("subtitle", ""))}</em>'
            f'<span class="shelf-facts">{len(b.chapters)} chapters · about {round(b.minutes / 60, 1)} h · {b.n_widgets} interactives</span>'
            f'</span></a>')
    main = f"""<div class="cover">
<section class="hero">
  <p class="eyebrow">{html.escape(SITE.get("eyebrow", ""))}</p>
  <h1>{html.escape(SITE["headline"][0])}<br><span>{html.escape(SITE["headline"][1])}</span></h1>
  <p class="hero-sub">{SITE["tagline_long"]}</p>
</section>
<section class="shelf" aria-label="Books">
  <h2>On the shelf</h2>
  <div class="shelf-grid">{''.join(cards)}</div>
</section>
<section class="how">
  <h2>What makes a book interactive</h2>
  <ol>{''.join(f"<li>{x}</li>" for x in SITE.get("principles", []))}</ol>
</section>
</div>"""
    return shell(f"{SITE['name']} · {SITE['tagline']}", SITE["tagline_long"], main, cls="is-home")


def check(book: Book) -> list[str]:
    errs, slugs = [], {c["slug"] for c in book.chapters}
    src = "".join((ENGINE / "assets" / a).read_text(encoding="utf-8") for a in ENGINE_JS)
    src += "".join((book.dir / "assets" / a).read_text(encoding="utf-8") for a in book.scripts)
    known = set(re.findall(r'MB\.widget\(\s*"([\w-]+)"', src))
    for w in book.cfg.get("brand", {}).get("widgets", []):
        if w not in known:
            errs.append(f"{book.slug}/book.json: unknown widget '{w}'")
    for c in book.chapters:
        where = f"{book.slug}/{c['file']}"
        for w in c["widgets"]:
            if w not in known:
                errs.append(f"{where}: unknown widget '{w}'")
        for href in re.findall(r'href="(/[^"#]*)', c["body"]):
            parts = href.strip("/").split("/")
            if parts[0] == book.slug and len(parts) > 1 and parts[1] not in slugs and parts[1] != "assets":
                errs.append(f"{where}: dead link {href}")
        for tag in ("pre", "details", "section", "aside", "table", "div", "ol", "ul"):
            a, b = len(re.findall(rf"<{tag}\b", c["body"])), len(re.findall(rf"</{tag}>", c["body"]))
            if a != b:
                errs.append(f"{where}: <{tag}> opened {a} times, closed {b}")
        if "—" in c["body"]:
            errs.append(f"{where}: contains an em dash")
        if not c["summary"]:
            errs.append(f"{where}: meta has no summary")
    return errs


def main() -> None:
    folders = sorted(p for p in BOOKS.iterdir() if (p / "book.json").exists())
    books = sorted((Book(p) for p in folders), key=lambda b: b.cfg.get("order", 99))
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "assets").mkdir(parents=True)
    for a in (ENGINE / "assets").iterdir():
        if a.is_file():
            shutil.copy(a, DIST / "assets" / a.name)
    errs = []
    for b in books:
        out = DIST / b.slug
        out.mkdir()
        if (b.dir / "assets").exists():
            shutil.copytree(b.dir / "assets", out / "assets")
        for c in b.chapters:
            (out / c["slug"]).mkdir()
            (out / c["slug"] / "index.html").write_text(chapter_page(b, c), encoding="utf-8")
        (out / "index.html").write_text(cover(b), encoding="utf-8")
        (out / "chapters.json").write_text(json.dumps(
            [{k: c[k] for k in ("slug", "n", "title", "part", "summary", "minutes", "words", "widgets")} for c in b.chapters],
            indent=1), encoding="utf-8")
        print(f"  {b.slug:<12} {len(b.chapters):>3} chapters  {sum(c['words'] for c in b.chapters):>7,} words  {b.n_widgets:>3} interactives")
        errs += check(b)
    shown = [b for b in books if not b.cfg.get("hidden")]
    (DIST / "index.html").write_text(home(shown), encoding="utf-8")
    (DIST / "books.json").write_text(json.dumps([{"slug": b.slug, "title": b.title, "chapters": len(b.chapters)} for b in books], indent=1))
    print(f"built {len(books)} books -> {DIST}")
    if "--check" in sys.argv:
        for e in errs:
            print("  !", e)
        if errs:
            raise SystemExit(f"{len(errs)} problems")
        print("check: ok")


if __name__ == "__main__":
    main()
