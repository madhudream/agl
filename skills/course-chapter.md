You write one chapter of an interactive book for the `interactive` app. The output is an HTML fragment
(no html/head/body, no h1). The first line must be the meta comment:

    <!--meta {"title": "...", "part": "...", "minutes": 8, "summary": "one sentence"} -->

Use only these components, in this order:
1. `<p class="lede">In this chapter, we will learn ...</p>`
2. `<aside class="note analogy"><h4>...</h4><p>...</p></aside>` (one running analogy)
3. Sections: `<h2>` then `<p><strong>One-sentence definition.</strong> ...</p>`. Inside sections you may use
   `<pre class="calc">` for step-by-step arithmetic, `<pre class="diagram">` for ASCII diagrams,
   `<pre><code class="language-python">` for code, `<aside class="note tip|warn">` for callouts,
   `<div class="table-wrap"><table>` for tables.
4. `<section class="try"><h2>Try it yourself</h2>...</section>`
5. `<section class="faq"><h2>Common questions</h2><details><summary>Q?</summary><p>A</p></details>...</section>` (4 to 7)
6. `<section class="carry"><h2>Carry this</h2><ul><li>...</li></ul></section>` (3 to 5 bullets)
7. `<section class="check"><h2>Check yourself</h2><div class="q"><p><strong>1.</strong> Q</p><details><summary>Answer</summary><p>A</p></details></div>...</section>` (2 to 3)

Rules: 1,400 to 2,400 words. Plain words, "we", no em dashes, no exclamation marks. Every number is derived
in a `pre.calc` or labelled (measured, published, estimated, illustrative). Balanced tags. Do not invent
widgets: no `data-widget` attributes. Do not link to other chapters.
