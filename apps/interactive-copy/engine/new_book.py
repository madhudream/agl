#!/usr/bin/env python3
"""Start a new interactive book:  python3 engine/new_book.py <slug> "Title: Subtitle line" """
import json
import re
import sys
from pathlib import Path

if len(sys.argv) < 3 or not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", sys.argv[1]):
    raise SystemExit('usage: python3 engine/new_book.py <slug> "Title: Second line"   (slug: lowercase letters, digits, dashes)')
slug, title = sys.argv[1], sys.argv[2]
root = Path(__file__).resolve().parent.parent / "books" / slug
if root.exists():
    raise SystemExit(f"books/{slug} already exists")
(root / "chapters").mkdir(parents=True)
(root / "assets").mkdir()
fn = "widgets-" + slug + ".js"
(root / "book.json").write_text(json.dumps({
    "slug": slug, "title": title, "short": title.split(":")[0], "eyebrow": "An interactive book", "order": 50, "hue": 150,
    "hidden": True, "subtitle": "One sentence that tells a stranger why to read this book.", "level": "no background needed",
    "scripts": [fn], "how": ["<b>In order.</b> Each chapter uses only what the earlier ones taught."],
    "parts": {"Part I": "What this part is about."}, "credits": ""}, indent=2) + "\n", encoding="utf-8")
(root / "assets" / fn).write_text('''/* Interactives of this book. One MB.widget(...) per interactive. See the guide: /make/03-making-an-interactive/ */
(function () {
  "use strict";
  var MB = window.MB, F = MB.fmt, h = MB.h;

  MB.widget("first-calculator", function (el, ui) {
    var st = {}, body = ui.frame("Title of the interactive", "What to move and what to watch."), out = h("div");
    body.appendChild(ui.controls([
      { key: "a", label: "How many", min: 0, max: 100, value: 10 },
      { key: "b", label: "Each costs", min: 1, max: 50, value: 5, fmt: F.usd }
    ], st, draw));
    body.appendChild(out);
    function draw() {
      var total = st.a * st.b;
      out.textContent = "";
      out.appendChild(ui.tiles([{ label: "Total", value: F.usd(total), kind: "hot" }]));
      out.appendChild(ui.calc([st.a + " x " + F.usd(st.b) + " = " + F.usd(total)]));
      ui.foot("One sentence that tells the reader what to notice.");
    }
    draw();
  });
})();
''', encoding="utf-8")
CH1 = '''<!--meta {"title": "The first idea", "part": "Part I", "minutes": 5, "summary": "One line that sells this chapter."} -->

<p class="lede">In this chapter, we will learn ...</p>

<aside class="note analogy">
<h4>The analogy: a title</h4>
<p>One picture from everyday life that the whole chapter can lean on.</p>
</aside>

<h2>The first section</h2>

<p><strong>A definition in one bold sentence.</strong> Then the explanation, in short sentences.</p>

<pre class="calc">how many     10
each costs   $5
total        10 x $5 = $50</pre>

<p>Before you move anything, guess the total for 40 items.</p>

<div class="widget" data-widget="first-calculator"></div>

<section class="try">
<h2>Try it yourself</h2>
<p>An experiment the reader can run, with the real output.</p>
</section>

<section class="faq">
<h2>Common questions</h2>
<details><summary>A question a reader still has?</summary><p>The answer, in two to five sentences.</p></details>
</section>

<section class="carry">
<h2>Carry this</h2>
<ul><li>The one line to remember.</li></ul>
</section>

<section class="check">
<h2>Check yourself</h2>
<div class="q"><p><strong>1.</strong> A question.</p>
<details><summary>Answer</summary><p>The answer.</p></details></div>
</section>
'''
(root / "chapters" / "01-the-first-idea.html").write_text(CH1, encoding="utf-8")
(root / "chapters" / "02-the-second-idea.html").write_text(
    CH1.replace("The first idea", "The second idea").replace('<div class="widget" data-widget="first-calculator"></div>\n\n', "")
       .replace("<p>Before you move anything, guess the total for 40 items.</p>\n\n", '<p>This builds on <a href="/01-the-first-idea/">Chapter 1</a>.</p>\n\n'),
    encoding="utf-8")
print(f'created books/{slug}/  (hidden from the shelf until you set "hidden": false in book.json)')
print(f"next:  python3 engine/build.py --check  &&  python3 -m http.server 8000 -d dist   ->  http://localhost:8000/{slug}/")
