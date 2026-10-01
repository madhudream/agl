/* Interactives of the agents book. One MB.widget(...) per interactive.
   whiteboard      renders the excalidraw file behind the book, slide by slide
   task-sorter     measurable or not, open or closed
   loop-sim        step through one real recorded loop run
   cost-calculator tokens x price for the models the book uses
   wave-scheduler  type a graph, see its waves
   pattern-picker  seven graph shapes, each in the text form the engine reads */
(function () {
  "use strict";
  var MB = window.MB, F = MB.fmt, h = MB.h;
  var NS = "http://www.w3.org/2000/svg";
  function s(tag, attrs, kids) {
    var el = document.createElementNS(NS, tag), k;
    for (k in attrs || {}) if (attrs[k] !== undefined && attrs[k] !== null) el.setAttribute(k, attrs[k]);
    (kids || []).forEach(function (c) { el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return el;
  }

  /* ---------- whiteboard: the excalidraw file, rendered as SVG ---------- */
  MB.widget("whiteboard", function (el, ui) {
    var data = MB.whiteboard, els = data.elements, files = data.files;
    var byId = {};
    els.forEach(function (e) { byId[e.id] = e; });
    // slides: sort by x, split where the horizontal gap is large
    var sorted = els.slice().sort(function (a, b) { return a.x - b.x; }), slides = [], cur = null, reach = -Infinity;
    sorted.forEach(function (e) {
      var x1 = e.x + (e.width || 0);
      if (cur && e.x - reach > 350) { slides.push(cur); cur = null; }
      if (!cur) { cur = []; }
      cur.push(e);
      reach = Math.max(reach, x1);
    });
    if (cur) slides.push(cur);
    // a bound text belongs to its container's slide (same bounds anyway); give each slide a title
    function title(sl) {
      var texts = sl.filter(function (e) { return e.type === "text" && e.text.trim(); });
      texts.sort(function (a, b) { return (b.fontSize || 0) - (a.fontSize || 0) || a.y - b.y; });
      var t = texts.length ? texts[0].text.split("\n")[0].replace(/[:]$/, "") : "untitled";
      return t.length > 34 ? t.slice(0, 32) + "…" : t;
    }
    var st = { i: 0 };
    var body = ui.frame("The whiteboard behind this book", "The class drawing, rendered from its .excalidraw file. Step through the boards; the chapters follow the same order.");
    var nav = h("div", { class: "w-row", style: "flex-wrap:wrap;gap:8px;align-items:center" });
    var prev = h("button", { class: "w-btn", type: "button", text: "← previous" }), next = h("button", { class: "w-btn", type: "button", text: "next →" });
    var label = h("span", { class: "mono", style: "font-size:13px;color:var(--ink-2)" });
    var pick = h("select", { "aria-label": "board", style: "max-width:100%;font:14px var(--ui);padding:6px 8px;border-radius:8px;border:1px solid var(--rule);background:var(--page);color:var(--ink)" });
    slides.forEach(function (sl, i) { pick.appendChild(h("option", { value: String(i), text: (i + 1) + ". " + title(sl) })); });
    pick.addEventListener("change", function () { st.i = +pick.value; draw(); });
    prev.addEventListener("click", function () { st.i = (st.i + slides.length - 1) % slides.length; draw(); });
    next.addEventListener("click", function () { st.i = (st.i + 1) % slides.length; draw(); });
    nav.appendChild(prev); nav.appendChild(next); nav.appendChild(pick); nav.appendChild(label);
    var stage = h("div", { class: "chart", style: "margin-top:10px;border:1px solid var(--rule);border-radius:12px;background:var(--page);padding:8px;color:var(--ink)" });
    body.appendChild(nav); body.appendChild(stage);

    function arrowPath(e) {
      var pts = e.points.map(function (p) { return [e.x + p[0], e.y + p[1]]; });
      if (pts.length < 2) return "";
      if (!e.roundness || pts.length === 2) return "M" + pts.map(function (p) { return p[0] + " " + p[1]; }).join(" L");
      var d = "M" + pts[0][0] + " " + pts[0][1];
      for (var i = 1; i < pts.length - 1; i++) {
        var mx = (pts[i][0] + pts[i + 1][0]) / 2, my = (pts[i][1] + pts[i + 1][1]) / 2;
        d += " Q" + pts[i][0] + " " + pts[i][1] + " " + mx + " " + my;
      }
      var last = pts[pts.length - 1];
      d += " L" + last[0] + " " + last[1];
      return d;
    }
    function head(e, g) {
      var pts = e.points, n = pts.length;
      if (n < 2) return;
      var ax = e.x + pts[n - 1][0], ay = e.y + pts[n - 1][1], bx = e.x + pts[n - 2][0], by = e.y + pts[n - 2][1];
      var ang = Math.atan2(ay - by, ax - bx), L = 14, w = 0.42;
      var p1 = [ax - L * Math.cos(ang - w), ay - L * Math.sin(ang - w)], p2 = [ax - L * Math.cos(ang + w), ay - L * Math.sin(ang + w)];
      g.appendChild(s("path", { d: "M" + p1[0] + " " + p1[1] + " L" + ax + " " + ay + " L" + p2[0] + " " + p2[1], fill: "none", stroke: "currentColor", "stroke-width": e.strokeWidth || 2, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    }
    function draw() {
      var sl = slides[st.i], pad = 40;
      var x0 = Math.min.apply(null, sl.map(function (e) { return e.x; })) - pad, y0 = Math.min.apply(null, sl.map(function (e) { return e.y; })) - pad;
      var x1 = Math.max.apply(null, sl.map(function (e) { return e.x + (e.width || 0); })) + pad, y1 = Math.max.apply(null, sl.map(function (e) { return e.y + (e.height || 0); })) + pad;
      var svg = s("svg", { viewBox: x0 + " " + y0 + " " + (x1 - x0) + " " + (y1 - y0), role: "img", "aria-label": "whiteboard board " + (st.i + 1), style: "max-height:70vh" });
      var g = s("g", { fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" });
      sl.forEach(function (e) {
        if (e.type === "rectangle") {
          g.appendChild(s("rect", { x: e.x, y: e.y, width: e.width, height: e.height, rx: e.roundness ? 14 : 2, "stroke-width": e.strokeWidth || 2,
            fill: e.backgroundColor && e.backgroundColor !== "transparent" ? e.backgroundColor : "none" }));
        } else if (e.type === "ellipse") {
          g.appendChild(s("ellipse", { cx: e.x + e.width / 2, cy: e.y + e.height / 2, rx: e.width / 2, ry: e.height / 2 }));
        } else if (e.type === "arrow" || e.type === "line") {
          g.appendChild(s("path", { d: arrowPath(e), "stroke-width": e.strokeWidth || 2 }));
          if (e.type === "arrow" && e.endArrowhead) head(e, g);
        } else if (e.type === "image") {
          var f = files[e.fileId];
          if (f) g.appendChild(s("image", { href: f.dataURL, x: e.x, y: e.y, width: e.width, height: e.height, preserveAspectRatio: "none" }));
        }
      });
      sl.forEach(function (e) {
        if (e.type !== "text") return;
        var fs = e.fontSize || 20, lh = (e.lineHeight || 1.25) * fs, lines = e.text.split("\n");
        var anchor = e.textAlign === "center" ? "middle" : e.textAlign === "right" ? "end" : "start";
        var x = e.textAlign === "center" ? e.x + e.width / 2 : e.textAlign === "right" ? e.x + e.width : e.x;
        var top = e.y + Math.max(0, (e.height - lines.length * lh) / 2);
        var t = s("text", { x: x, y: top, "text-anchor": anchor, fill: "currentColor", stroke: "none",
          style: "font-family:'Excalifont','Virgil','Segoe Print','Bradley Hand','Comic Sans MS',cursive;font-size:" + fs + "px;white-space:pre" });
        lines.forEach(function (line, i) {
          t.appendChild(s("tspan", { x: x, y: top + lh * i + fs * 0.9 }, [line || " "]));
        });
        g.appendChild(t);
      });
      svg.appendChild(g);
      stage.textContent = "";
      stage.appendChild(svg);
      pick.value = String(st.i);
      label.textContent = "board " + (st.i + 1) + " of " + slides.length + " · " + sl.length + " elements";
      ui.foot("Twelve boards, left to right, in the order the class drew them: the title and the two quotes, the two kinds of tasks, the coding agent and its project folder, the loop, the graph, the setup steps, the examples, autoresearch, and /goal. The arrows are the lesson: a loop goes round, a graph goes forward.");
    }
    draw();
  });

  /* ---------- task-sorter ---------- */
  MB.widget("task-sorter", function (el, ui) {
    var items = [
      { t: "Reduce the web page load time.", a: "measurable", w: "Milliseconds on a fixed page. A loop can own this." },
      { t: "Implement dark mode.", a: "not", w: "Done or not done, by a human's eye. A judge or a person has to say pass." },
      { t: "Reduce the memory footprint of the app.", a: "measurable", w: "Megabytes at peak. Measure, change, measure." },
      { t: "Integrate the payment gateway.", a: "not", w: "Works or does not. There is no number to lower every run." },
      { t: "Get the lowest validation loss in five minutes of training.", a: "measurable", w: "This is autoresearch's exact task. One number, fixed budget." },
      { t: "Make the onboarding feel friendlier.", a: "not", w: "Until you define a score for it (a survey, a drop-off rate), it is taste." },
      { t: "Raise the pass rate of the 12-task exam.", a: "measurable", w: "This book's own loop. Score, cost and latency are all numbers." },
      { t: "Reduce the latency of the search endpoint.", a: "measurable", w: "p50 and p95 in milliseconds. Classic." },
      { t: "Write better documentation.", a: "not", w: "Better for whom? Pin it to a measurable proxy first, or hand it to a reviewer." },
      { t: "Cut the dollar cost of one course build.", a: "measurable", w: "The model API reports cost per call. We cut the course judge's cost this way." }
    ];
    var opts = [["measurable", "Measurable"], ["not", "Non-measurable"]], pick = {}, shown = false;
    var body = ui.frame("Sort ten tasks", "Can a program print one number after every attempt, so that a loop can keep or discard on its own?");
    var list = h("div"), out = h("div");
    var btn = h("button", { class: "w-btn primary", type: "button", text: "Check my sorting" });
    btn.addEventListener("click", function () { shown = true; draw(); });
    body.appendChild(list); body.appendChild(h("div", { class: "w-row", style: "margin-top:12px" }, [btn])); body.appendChild(out);
    function draw() {
      list.textContent = "";
      items.forEach(function (it, i) {
        var right = pick[i] === it.a;
        var row = h("div", { class: "line-item" + (shown ? (right ? " is-right" : " is-wrong") : ""), style: "flex-wrap:wrap" }, [h("span", { class: "txt", text: it.t })]);
        row.appendChild(ui.segmented(opts.map(function (o) { return { value: o[0], label: o[1] }; }), pick[i], function (v) { pick[i] = v; if (shown) draw(); }, "category for task " + (i + 1)));
        if (shown) row.appendChild(h("div", { style: "flex-basis:100%;font-size:13.5px;color:var(--ink-2)" }, [MB.badge(it.a === "measurable" ? "Measurable" : "Non-measurable", it.a === "measurable" ? "good" : "drop"), " " + it.w]));
        list.appendChild(row);
      });
      out.textContent = "";
      if (shown) {
        var n = items.filter(function (it, i) { return pick[i] === it.a; }).length;
        out.appendChild(h("div", { style: "height:12px" }));
        out.appendChild(ui.tiles([{ label: "You sorted correctly", value: n + " of " + items.length, kind: n >= 8 ? "good" : "hot" }]));
        ui.foot("Measurable tasks can run inside an autonomous loop. Non-measurable tasks need a judge first: either a person or a model with a rubric. Building that judge is step one, not step last.");
      }
    }
    draw();
  });

  /* ---------- loop-sim: one real recorded run ---------- */
  MB.widget("loop-sim", function (el, ui) {
    // the recorded run from examples/loop_hello.py (tokens, ms and dollars are from the trace)
    var steps = [
      { kind: "llm", text: "The model reads the task and the two tool schemas. It decides it needs the file.", call: "read_file(path=\"agl/loop.py\", start=1, end=1000)", pt: 475, ct: 531, ms: 7901, usd: 0.00008 },
      { kind: "tool", text: "Action and Result: the tool runs and its text goes back into the history as a tool message.", result: "217 numbered lines of agl/loop.py (about 3,500 tokens)" },
      { kind: "llm", text: "The model sees the file. The prompt is now 3,970 tokens: tool results grow the context. It asks for the arithmetic.", call: "calc(expression=\"217 * 7\")", pt: 3970, ct: 51, ms: 1238, usd: 0.00013 },
      { kind: "tool", text: "The calculator answers exactly. No mental math.", result: "1519" },
      { kind: "llm", text: "No tool call this time: the reply is a candidate answer, so it goes to Evaluate.", answer: "1519", pt: 4022, ct: 11, ms: 1563, usd: 0.00003 },
      { kind: "evaluate", text: "The evaluator is a plain function: is the answer a bare number? Yes. Pass. Final answer." }
    ];
    var st = { i: 0, strict: "check" };
    var body = ui.frame("Step through one real loop run", "Task: how many lines does agl/loop.py have, multiplied by 7? Reply with only the number. Worker: the lab's flash-class model.");
    var row = h("div", { class: "w-row", style: "flex-wrap:wrap;gap:8px;align-items:center" });
    var step = h("button", { class: "w-btn primary", type: "button", text: "Step →" }), reset = h("button", { class: "w-btn", type: "button", text: "Reset" });
    step.addEventListener("click", function () { if (st.i < steps.length) st.i++; draw(); });
    reset.addEventListener("click", function () { st.i = 0; draw(); });
    row.appendChild(step); row.appendChild(reset);
    row.appendChild(ui.segmented([{ value: "none", label: "No evaluator" }, { value: "check", label: "Deterministic check" }, { value: "judge", label: "LLM judge" }], st.strict, function (v) { st.strict = v; draw(); }, "evaluator"));
    var out = h("div"), tiles = h("div");
    body.appendChild(row); body.appendChild(tiles); body.appendChild(out);
    function draw() {
      out.textContent = ""; tiles.textContent = "";
      var pt = 0, ct = 0, ms = 0, usd = 0, calls = 0;
      steps.slice(0, st.i).forEach(function (sp, i) {
        if (sp.kind === "llm") { pt += sp.pt; ct += sp.ct; ms += sp.ms; usd += sp.usd; calls++; }
        var box = h("div", { class: "line-item", style: "flex-wrap:wrap;align-items:flex-start" });
        var tag = sp.kind === "llm" ? "LLM" : sp.kind === "tool" ? "Action → Result" : "Evaluate";
        box.appendChild(MB.badge(tag, sp.kind === "llm" ? "semantic" : sp.kind === "tool" ? "episodic" : "good"));
        var txt = sp.text;
        if (sp.kind === "evaluate") {
          if (st.strict === "none") txt = "No evaluator: whatever the model said is the final answer. Cheap, and wrong answers pass too.";
          if (st.strict === "judge") txt = "An LLM judge reads the task and the answer against a rubric and returns a score. One more call, about $0.0003 here, and it can read prose a regex cannot. Pass.";
        }
        box.appendChild(h("span", { class: "txt", style: "flex:1 1 60%", text: txt }));
        if (sp.call) box.appendChild(h("code", { style: "flex-basis:100%;font-size:12.5px", text: "→ " + sp.call }));
        if (sp.result) box.appendChild(h("code", { style: "flex-basis:100%;font-size:12.5px", text: "⇒ " + sp.result }));
        if (sp.answer) box.appendChild(h("code", { style: "flex-basis:100%;font-size:12.5px", text: "“" + sp.answer + "”" }));
        if (sp.kind === "llm") box.appendChild(h("span", { class: "mono", style: "flex-basis:100%;font-size:12px;color:var(--ink-3)", text: sp.pt + " prompt + " + sp.ct + " completion tokens · " + F.ms(sp.ms) + " · " + F.usd(sp.usd) }));
        out.appendChild(box);
      });
      if (st.strict === "judge" && st.i === steps.length) { usd += 0.0003; calls++; ms += 1800; }
      tiles.appendChild(ui.tiles([
        { label: "LLM calls", value: String(calls) },
        { label: "Prompt tokens", value: F.int(pt), note: "grows with every tool result" },
        { label: "Completion tokens", value: F.int(ct) },
        { label: "Wall clock", value: F.ms(ms) },
        { label: "Cost", value: F.usd(usd), kind: "hot" }
      ]));
      if (st.i === steps.length) {
        out.appendChild(ui.calc([
          "prompt tokens   475 + 3,970 + 4,022 = " + F.int(475 + 3970 + 4022),
          "why the jump    step 2 carries the whole file the tool returned (about 3,500 tokens)",
          "cost            $0.00008 + $0.00013 + $0.00003 = $0.00024" + (st.strict === "judge" ? " + $0.0003 judge" : "")
        ]));
        ui.foot(st.strict === "none" ? "Without an evaluator the loop is just 'call tools until the model stops'. It works until the day it does not, and nobody notices." :
          st.strict === "check" ? "A deterministic check costs nothing and never hallucinates. Use one whenever the answer has a shape you can test." :
          "The judge roughly doubled the cost of this tiny run. Judges are for answers without a testable shape: prose, plans, chapters. Cheap checks first, judge last.");
      } else {
        step.disabled = false;
        ui.foot("Press Step. Watch the prompt tokens.");
      }
      step.disabled = st.i >= steps.length;
    }
    draw();
  });

  /* ---------- cost-calculator ---------- */
  MB.widget("cost-calculator", function (el, ui) {
    // $ per million tokens, list prices on 2026-10-01
    var models = [
      { id: "ChatGPT 6 Luna", pin: 0.10, pout: 0.50, note: "a flash-class model: the kind the lab runs used" },
      { id: "ChatGPT 5 nano", pin: 0.20, pout: 1.25, note: "small and fast" },
      { id: "ChatGPT 5 mini", pin: 0.75, pout: 4.50, note: "the code's default worker" },
      { id: "ChatGPT 5", pin: 5.00, pout: 30.00, note: "the code's default judge" },
      { id: "ChatGPT Astra", pin: 10.00, pout: 50.00, note: "a frontier model: the default specialist" }
    ];
    var st = { m: 0 };
    var body = ui.frame("What does a loop cost?", "Tokens times price. The prompt grows with every tool result, so prompt tokens dominate.");
    body.appendChild(ui.segmented(models.map(function (m, i) { return { value: i, label: m.id }; }), 0, function (v) { st.m = +v; draw(); }, "model"));
    var out = h("div");
    body.appendChild(ui.controls([
      { key: "pt", label: "Prompt tokens per call", min: 200, max: 60000, step: 100, value: 4000, fmt: F.int, log: true },
      { key: "ct", label: "Completion tokens per call", min: 10, max: 8000, step: 10, value: 300, fmt: F.int, log: true },
      { key: "calls", label: "LLM calls per task", min: 1, max: 20, value: 3 },
      { key: "tasks", label: "Tasks per day", min: 1, max: 10000, value: 100, log: true }
    ], st, draw));
    body.appendChild(out);
    function draw() {
      var m = models[st.m];
      var perCall = st.pt / 1e6 * m.pin + st.ct / 1e6 * m.pout, perTask = perCall * st.calls, perDay = perTask * st.tasks, perMonth = perDay * 30;
      out.textContent = "";
      out.appendChild(ui.tiles([
        { label: "Per call", value: F.usd(perCall) },
        { label: "Per task", value: F.usd(perTask) },
        { label: "Per day", value: F.usd(perDay), kind: "hot" },
        { label: "Per month", value: F.usd(perMonth), kind: perMonth > 100 ? "bad" : "good" }
      ]));
      out.appendChild(ui.calc([
        "per call    " + F.int(st.pt) + " / 1M x $" + m.pin.toFixed(2) + " + " + F.int(st.ct) + " / 1M x $" + m.pout.toFixed(2) + " = " + F.usd(perCall),
        "per task    " + F.usd(perCall) + " x " + st.calls + " calls = " + F.usd(perTask),
        "per day     " + F.usd(perTask) + " x " + F.int(st.tasks) + " tasks = " + F.usd(perDay),
        "per month   " + F.usd(perDay) + " x 30 = " + F.usd(perMonth)
      ]));
      ui.foot(m.id + ": " + m.note + ". The 12-task exam cost $0.0086 on a flash-class worker: cheap enough to run after every change, which is the whole point of a cheap worker.");
    }
    draw();
  });

  /* ---------- wave-scheduler ---------- */
  MB.widget("wave-scheduler", function (el, ui) {
    var sample = "START -> plan\nplan -> write_a, write_b, write_c\nwrite_a, write_b, write_c -> edit\nedit -> review\nreview ?pass-> END\nreview ?fail-> edit";
    var body = ui.frame("Type a graph, see its waves", "Edges like  a -> b, c  mean: when a finishes, b and c may start. Nodes whose inputs have all arrived run in the same wave, in parallel.");
    var ta = h("textarea", { rows: 7, spellcheck: "false", style: "width:100%;font:13.5px var(--mono);padding:10px;border-radius:10px;border:1px solid var(--rule);background:var(--page);color:var(--ink);resize:vertical" });
    ta.value = sample;
    var out = h("div");
    body.appendChild(ta); body.appendChild(out);
    ta.addEventListener("input", draw);
    function parse(text) {
      var edges = [], nodes = {}, routers = [], err = null;
      text.split("\n").forEach(function (raw) {
        var line = raw.split("#")[0].trim();
        if (!line) return;
        var r = line.match(/^(\w+)\s*\?(\w+)->\s*(.+)$/);
        if (r) { routers.push([r[1], r[2], r[3].split(",").map(function (x) { return x.trim(); })]); nodes[r[1]] = 1; return; }
        var m = line.match(/^(.+?)\s*->\s*(.+)$/);
        if (!m) { err = "cannot read: " + raw; return; }
        m[1].split(",").forEach(function (a) {
          m[2].split(",").forEach(function (b) {
            a = a.trim(); b = b.trim();
            edges.push([a, b]);
            if (a !== "START" && a !== "END") nodes[a] = 1;
            if (b !== "START" && b !== "END") nodes[b] = 1;
          });
        });
      });
      return { edges: edges, nodes: Object.keys(nodes), routers: routers, err: err };
    }
    function waves(g) {
      var deps = {}, done = {}, out = [], left = g.nodes.slice();
      g.nodes.forEach(function (n) { deps[n] = []; });
      g.edges.forEach(function (e) { if (e[1] !== "END" && e[0] !== "START") deps[e[1]].push(e[0]); });
      var started = g.edges.filter(function (e) { return e[0] === "START"; }).map(function (e) { return e[1]; });
      var guard = 0;
      while (left.length && guard++ < 50) {
        var ready = left.filter(function (n) { return (deps[n].length === 0 ? started.indexOf(n) >= 0 : deps[n].every(function (d) { return done[d]; })); });
        if (!ready.length) break;
        out.push(ready);
        ready.forEach(function (n) { done[n] = 1; });
        left = left.filter(function (n) { return !done[n]; });
      }
      return { waves: out, stuck: left };
    }
    function draw() {
      var g = parse(ta.value), w = waves(g);
      out.textContent = "";
      if (g.err) { out.appendChild(h("p", { class: "w-err", text: g.err })); return; }
      var rows = h("div", { style: "margin:12px 0" });
      w.waves.forEach(function (wave, i) {
        var line = h("div", { class: "line-item", style: "flex-wrap:wrap;align-items:center" }, [h("span", { class: "mono", style: "min-width:72px;color:var(--ink-3)", text: "wave " + (i + 1) })]);
        wave.forEach(function (n) { line.appendChild(h("span", { class: "chip", style: "background:var(--raise);border-color:var(--rule-2)", text: n })); });
        if (wave.length > 1) line.appendChild(h("span", { style: "font-size:12.5px;color:var(--ink-2)", text: wave.length + " nodes in parallel" }));
        rows.appendChild(line);
      });
      if (w.stuck.length) rows.appendChild(h("p", { class: "w-err", text: "never ready (no path from START, or a cycle without a router): " + w.stuck.join(", ") }));
      g.routers.forEach(function (r) {
        rows.appendChild(h("div", { class: "line-item" }, [h("span", { class: "mono", style: "min-width:72px;color:var(--ink-3)", text: "router" }), h("span", { class: "txt", text: r[0] + " --" + r[1] + "--> " + r[2].join(", ") })]));
      });
      out.appendChild(rows);
      var seq = g.nodes.length, par = w.waves.length;
      out.appendChild(ui.tiles([
        { label: "Nodes", value: String(seq) },
        { label: "Waves", value: String(par), kind: "hot" },
        { label: "If every node took 1 minute", value: par + " min instead of " + seq, note: "wall clock in waves vs one after another" }
      ]));
      ui.foot("Fan-out is free parallelism; fan-in is a wait. Routers (the ?label-> lines) are decided at run time from the state, so they do not appear in the static waves. A back edge like review ?fail-> edit re-triggers a node; it is not an input the node waits for.");
    }
    draw();
  });

  /* ---------- pattern-picker ---------- */
  MB.widget("pattern-picker", function (el, ui) {
    var patterns = [
      { k: "sequence", name: "Sequence", when: "The steps are known and each needs the last one's output.",
        dsl: "START -> extract\nextract -> transform\ntransform -> load\nload -> END",
        ex: "Document extraction: pull fields, normalise them, write the record.", eval: "A schema check on the record, then a sample judged against the source." },
      { k: "fanout", name: "Fan-out, fan-in", when: "Several independent pieces of work, then one step that needs all of them.",
        dsl: "START -> plan\nplan -> write_a, write_b, write_c\nwrite_a, write_b, write_c -> edit\nedit -> END",
        ex: "A report with three sections written in parallel and merged by an editor.", eval: "Each section against its brief; the merged report against a coherence rubric." },
      { k: "map", name: "Map over a list", when: "The same work for every item in a list whose length is known only at run time.",
        dsl: "START -> outline\noutline -> write   # write = fanout(write_one, over='chapters', into='drafts')\nwrite -> assemble\nassemble -> END",
        ex: "One writer per chapter of a course; one summariser per ticket in a queue.", eval: "A validator on every item before it is collected." },
      { k: "router", name: "Router", when: "The next step depends on what the input turns out to be.",
        dsl: "START -> classify\nclassify ?billing-> billing\nclassify ?bug-> bug\nclassify ?other-> reply\nbilling, bug -> reply\nreply -> END",
        ex: "Support triage: classify a ticket, hand it to the right handler, draft the reply.", eval: "The classifier against a labelled set; replies against a policy check." },
      { k: "review", name: "Review cycle", when: "The output needs a reader's verdict and a chance to fix it.",
        dsl: "START -> draft\ndraft -> review\nreview ?pass-> END\nreview ?fail-> draft",
        ex: "A code-review bot: propose a change, have a second model review it, revise.", eval: "The review rubric, on a different model from the drafter; max_visits caps the cycle." },
      { k: "repair", name: "Build check and repair", when: "A program can say whether the output is acceptable, and a fix should target only what failed.",
        dsl: "START -> write\nwrite -> assemble\nassemble -> build_check\nbuild_check ?ok-> END\nbuild_check ?fail-> fix\nfix -> assemble",
        ex: "Generated code or content that must pass tests or a site build before it ships.", eval: "The real tests or build. The strongest evaluator there is." },
      { k: "subgraph", name: "Sub-graph as a node", when: "A whole workflow repeated inside a bigger one.",
        dsl: "START -> list_targets\nlist_targets -> research   # research = fanout(research_one_graph.as_node(), ...)\nresearch -> rank\nrank -> END",
        ex: "Research fifty companies with the same five-step graph each, then rank.", eval: "Each sub-graph's own checks, plus a ranking rubric at the end." }
    ];
    var st = { k: "fanout" };
    var body = ui.frame("Pick the shape of your problem", "Seven graph patterns. Each one is a few lines in the text form the engine reads; Part III builds them, Part V applies them.");
    body.appendChild(ui.segmented(patterns.map(function (p) { return { value: p.k, label: p.name }; }), st.k, function (v) { st.k = v; draw(); }, "pattern"));
    var out = h("div", { style: "margin-top:12px" });
    body.appendChild(out);
    function draw() {
      var p = patterns.filter(function (x) { return x.k === st.k; })[0];
      out.textContent = "";
      out.appendChild(h("p", { style: "margin:0 0 8px" }, [h("strong", { text: "When: " }), p.when]));
      out.appendChild(h("pre", { class: "diagram", style: "margin:8px 0", text: p.dsl }));
      out.appendChild(h("p", { style: "margin:8px 0" }, [h("strong", { text: "Example: " }), p.ex]));
      out.appendChild(h("p", { style: "margin:8px 0" }, [h("strong", { text: "Evaluate: " }), p.eval]));
      ui.foot("Lines with -> are edges: when the left side finishes, the right side may run. Lines with ?label-> are routers: a function of the state picks the label at run time. Nodes on one line after an arrow run in the same wave, in parallel.");
    }
    draw();
  });
})();
