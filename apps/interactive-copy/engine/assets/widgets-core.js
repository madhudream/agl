/* Widget runtime: registry, controls, number formatting and small SVG charts.
   A widget is MB.widget("name", function (el, ui) { ... }). It mounts on <div class="widget" data-widget="name">. */
(function () {
  "use strict";
  var MB = window.MB = window.MB || {};
  var registry = {};
  MB.widget = function (name, fn) { registry[name] = fn; };

  // ---------- formatting ----------
  MB.fmt = {
    int: function (n) { return Math.round(n).toLocaleString("en-US"); },
    num: function (n, d) { return Number(n).toLocaleString("en-US", { minimumFractionDigits: d || 0, maximumFractionDigits: d === undefined ? 2 : d }); },
    usd: function (n) {
      var a = Math.abs(n);
      if (a >= 1000) return "$" + Math.round(n).toLocaleString("en-US");
      if (a >= 1) return "$" + n.toFixed(2);
      if (a >= 0.01) return "$" + n.toFixed(3);
      if (a === 0) return "$0";
      return "$" + n.toPrecision(2).replace(/0+$/, "");
    },
    compact: function (n) {
      var a = Math.abs(n);
      if (a >= 1e12) return (n / 1e12).toFixed(a >= 1e13 ? 0 : 1) + "T";
      if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 0 : 1) + "B";
      if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
      if (a >= 1e4) return (n / 1e3).toFixed(a >= 1e5 ? 0 : 1) + "K";
      return MB.fmt.int(n);
    },
    bytes: function (b) {
      var u = ["B", "KB", "MB", "GB", "TB", "PB"], i = 0;
      while (b >= 1000 && i < u.length - 1) { b /= 1000; i++; }
      return (b >= 100 || i === 0 ? Math.round(b) : b.toFixed(1)) + " " + u[i];
    },
    ms: function (n) { return n >= 1000 ? (n / 1000).toFixed(2) + " s" : Math.round(n) + " ms"; },
    pct: function (n, d) { return n.toFixed(d === undefined ? 1 : d) + "%"; },
    pad: function (s, n, left) { s = String(s); while (s.length < n) s = left ? " " + s : s + " "; return s; }
  };

  // ---------- dom ----------
  function h(tag, attrs, kids) {
    var el = document.createElement(tag), k;
    attrs = attrs || {};
    for (k in attrs) {
      if (!Object.prototype.hasOwnProperty.call(attrs, k) || attrs[k] === undefined || attrs[k] === null || attrs[k] === false) continue;
      if (k === "class") el.className = attrs[k];
      else if (k === "text") el.textContent = attrs[k];
      else if (k === "html") el.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
      else el.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    }
    (Array.isArray(kids) ? kids : kids === undefined ? [] : [kids]).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return el;
  }
  MB.h = h;
  MB.esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

  var uid = 0;
  function UI(el, name) { this.el = el; this.name = name; }
  UI.prototype.frame = function (title, sub) {
    var body = h("div", { class: "w-body" }), foot = h("div", { class: "w-foot", hidden: true });
    this.el.textContent = "";
    this.el.appendChild(h("div", { class: "w" }, [
      h("div", { class: "w-head" }, [h("span", { class: "w-tag", text: "Try it" }), h("h3", { class: "w-title", text: title }),
        sub ? h("p", { class: "w-sub", text: sub }) : null]), body, foot]));
    this.body = body; this.footEl = foot;
    return body;
  };
  UI.prototype.foot = function (html) { this.footEl.hidden = !html; this.footEl.innerHTML = html || ""; };
  /* slider: {key,label,min,max,step,value,fmt,hint,log}. log sliders move through powers smoothly. */
  UI.prototype.controls = function (specs, state, onChange) {
    var grid = h("div", { class: "ctl-grid" });
    specs.forEach(function (s) {
      var id = "mb-c" + (++uid), f = s.fmt || MB.fmt.int;
      if (state[s.key] === undefined) state[s.key] = s.value;
      var toPos = s.log ? function (v) { return Math.log(v / s.min) / Math.log(s.max / s.min) * 1000; } : null;
      var fromPos = s.log ? function (p) {
        var v = s.min * Math.pow(s.max / s.min, p / 1000), mag = Math.pow(10, Math.floor(Math.log10(v)) - 1);
        return Math.min(s.max, Math.max(s.min, Math.round(v / mag) * mag));
      } : null;
      var out = h("output", { for: id, text: f(state[s.key]) });
      var input = h("input", { type: "range", id: id, min: s.log ? 0 : s.min, max: s.log ? 1000 : s.max, step: s.log ? 1 : (s.step || 1),
        value: s.log ? toPos(state[s.key]) : state[s.key], "aria-label": s.label });
      input.addEventListener("input", function () {
        state[s.key] = s.log ? fromPos(+input.value) : +input.value;
        out.textContent = f(state[s.key]);
        onChange(s.key);
      });
      grid.appendChild(h("div", { class: "ctl" }, [h("label", { for: id }, [h("span", { text: s.label }), out]), input,
        s.hint ? h("small", { text: s.hint }) : null]));
    });
    return grid;
  };
  UI.prototype.segmented = function (options, value, onPick, label) {
    var wrap = h("div", { class: "seg", role: "group", "aria-label": label || "options" });
    options.forEach(function (o) {
      var v = typeof o === "string" ? o : o.value, t = typeof o === "string" ? o : o.label;
      var b = h("button", { type: "button", "aria-pressed": String(v === value), text: t });
      b.addEventListener("click", function () {
        wrap.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
        b.setAttribute("aria-pressed", "true");
        onPick(v);
      });
      wrap.appendChild(b);
    });
    return wrap;
  };
  UI.prototype.tiles = function (items) {
    return h("div", { class: "tiles" }, items.map(function (t) {
      return h("div", { class: "tile" + (t.kind ? " " + t.kind : "") }, [h("p", { class: "tile-l", text: t.label }),
        h("p", { class: "tile-v", text: t.value }), t.note ? h("p", { class: "tile-d", text: t.note }) : null]);
    }));
  };
  UI.prototype.calc = function (lines) { return h("pre", { class: "w-calc", text: lines.join("\n") }); };
  UI.prototype.table = function (cols, rows, rowClass) {
    var t = h("table", { class: "w-table" }, [h("thead", {}, h("tr", {}, cols.map(function (c) {
      return h("th", { class: c.num ? "num" : null, text: c.label }); })))]);
    var tb = h("tbody");
    rows.forEach(function (r, i) {
      tb.appendChild(h("tr", { class: rowClass ? rowClass(r, i) : null }, cols.map(function (c) {
        var v = c.get(r, i);
        return h("td", { class: c.num ? "num" : null }, v instanceof Node ? v : String(v));
      })));
    });
    t.appendChild(tb);
    return h("div", { class: "w-scroll" }, t);
  };
  MB.badge = function (text, kind) { return h("span", { class: "badge " + (kind || ""), text: text }); };

  // ---------- charts (SVG, one axis, hover layer) ----------
  var NS = "http://www.w3.org/2000/svg";
  function s(tag, attrs, kids) {
    var el = document.createElementNS(NS, tag), k;
    for (k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k) && attrs[k] !== undefined) el.setAttribute(k, attrs[k]);
    (kids || []).forEach(function (c) { el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return el;
  }
  MB.svg = s;
  function ticks(lo, hi, n) {
    var span = hi - lo || 1, step = Math.pow(10, Math.floor(Math.log10(span / n))), err = span / n / step;
    step *= err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
    var out = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi + step * 1e-6; v += step) out.push(+v.toFixed(10));
    return out;
  }
  MB.ticks = ticks;
  var SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"];
  MB.series = SERIES;

  function tipFor(wrap) {
    var tip = h("div", { class: "tip", role: "status" });
    wrap.appendChild(tip);
    return {
      show: function (html, x, y) {
        tip.innerHTML = html; tip.classList.add("on");
        var w = wrap.clientWidth, tw = tip.offsetWidth;
        tip.style.left = Math.max(0, Math.min(w - tw, x + 12)) + "px";
        tip.style.top = Math.max(0, y - tip.offsetHeight - 10) + "px";
      },
      hide: function () { tip.classList.remove("on"); }
    };
  }
  MB.tipFor = tipFor;

  /* lineChart({series:[{name,points:[[x,y]..]}], xLabel, yLabel, xFmt, yFmt, yMin, yMax, height, marks:[{x,label}]}) */
  MB.lineChart = function (o) {
    var W = 680, H = o.height || 310, m = { l: 58, r: 22, t: 30, b: 42 }, wrap = h("div", { class: "chart" });
    var xs = [], ys = [];
    o.series.forEach(function (se) { se.points.forEach(function (p) { xs.push(p[0]); ys.push(p[1]); }); });
    var x0 = o.xMin !== undefined ? o.xMin : Math.min.apply(null, xs), x1 = o.xMax !== undefined ? o.xMax : Math.max.apply(null, xs);
    var y0 = o.yMin !== undefined ? o.yMin : 0, y1 = o.yMax !== undefined ? o.yMax : Math.max.apply(null, ys) * 1.08 || 1;
    if (x1 === x0) x1 = x0 + 1;
    var X = function (v) { return m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r); }, Y = function (v) { return H - m.b - (v - y0) / (y1 - y0) * (H - m.t - m.b); };
    var xf = o.xFmt || MB.fmt.compact, yf = o.yFmt || MB.fmt.compact;
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": o.title || "chart" });
    ticks(y0, y1, 5).forEach(function (t) {
      svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: "var(--grid)", "stroke-width": 1 }));
      svg.appendChild(s("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, [yf(t)]));
    });
    (o.xTicks || ticks(x0, x1, 6)).forEach(function (t) {
      svg.appendChild(s("text", { x: X(t), y: H - m.b + 18, "text-anchor": "middle" }, [xf(t)]));
    });
    svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: Y(y0), y2: Y(y0), stroke: "var(--axis)", "stroke-width": 1 }));
    if (o.xLabel) svg.appendChild(s("text", { x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle", class: "lab" }, [o.xLabel]));
    if (o.yLabel) svg.appendChild(s("text", { x: 12, y: 14, class: "lab" }, [o.yLabel]));
    (o.marks || []).forEach(function (mk) {
      svg.appendChild(s("line", { x1: X(mk.x), x2: X(mk.x), y1: m.t, y2: H - m.b, stroke: "var(--axis)", "stroke-width": 1 }));
      svg.appendChild(s("text", { x: X(mk.x) + (X(mk.x) > W - 90 ? -5 : 5), y: m.t + 10, "text-anchor": X(mk.x) > W - 90 ? "end" : "start", class: "lab" }, [mk.label]));
    });
    o.series.forEach(function (se, i) {
      var col = se.color || SERIES[i % SERIES.length];
      var d = se.points.map(function (p, j) { return (j ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(Math.min(y1, p[1])).toFixed(1); }).join(" ");
      svg.appendChild(s("path", { d: d, fill: "none", stroke: col, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      if (se.dots) se.points.forEach(function (p) {
        svg.appendChild(s("circle", { cx: X(p[0]), cy: Y(p[1]), r: 4.5, fill: col, stroke: "var(--raise)", "stroke-width": 2 }));
      });
      var last = se.points[se.points.length - 1];
      if (o.endLabels !== false && last) svg.appendChild(s("text", { x: Math.min(W - m.r - 4, X(last[0])) - 6, y: Y(Math.min(y1, last[1])) - 9, "text-anchor": "end", class: "lab" }, [se.name]));
    });
    var cross = s("line", { y1: m.t, y2: H - m.b, stroke: "var(--ink-3)", "stroke-width": 1, opacity: 0 });
    svg.appendChild(cross);
    var hit = s("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
    svg.appendChild(hit);
    if (o.series.length > 1) wrap.appendChild(h("div", { class: "legend" }, o.series.map(function (se, i) {
      return h("span", {}, [h("i", { style: "background:" + (se.color || SERIES[i % SERIES.length]) }), se.name]); })));
    wrap.appendChild(svg);
    var tip = tipFor(wrap);
    function move(ev) {
      var r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * W, xv = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
      var base = o.series[0].points, best = base[0];
      base.forEach(function (p) { if (Math.abs(p[0] - xv) < Math.abs(best[0] - xv)) best = p; });
      cross.setAttribute("x1", X(best[0])); cross.setAttribute("x2", X(best[0])); cross.setAttribute("opacity", 1);
      var html = "<b>" + (o.xLabel ? o.xLabel + " " : "") + xf(best[0]) + "</b>" + o.series.map(function (se) {
        var p = se.points.reduce(function (a, b) { return Math.abs(b[0] - best[0]) < Math.abs(a[0] - best[0]) ? b : a; });
        return MB.esc(se.name) + ": " + yf(p[1]);
      }).join("<br>");
      tip.show(html, X(best[0]) / W * r.width, (ev.clientY - r.top));
    }
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerleave", function () { cross.setAttribute("opacity", 0); tip.hide(); });
    return wrap;
  };

  /* barList({rows:[{label,value,note,color}], fmt, max}) : horizontal bars, value at the tip */
  MB.barList = function (o) {
    var max = o.max || Math.max.apply(null, o.rows.map(function (r) { return r.value; })) || 1, f = o.fmt || MB.fmt.compact;
    var wrap = h("div", { class: "chart" });
    o.rows.forEach(function (r) {
      var pct = Math.max(0.4, r.value / max * 100);
      wrap.appendChild(h("div", { style: "display:grid;grid-template-columns:minmax(90px,34%) 1fr;gap:10px;align-items:center;margin:0 0 8px" }, [
        h("div", { style: "font-size:13.5px;color:var(--ink-2)", text: r.label }),
        h("div", { style: "display:flex;align-items:center;gap:8px;min-width:0" }, [
          h("div", { style: "height:16px;border-radius:0 4px 4px 0;flex:0 0 auto;width:calc(" + pct.toFixed(2) + "% - 90px);min-width:2px;background:" + (r.color || "var(--s1)"),
            title: r.label + ": " + f(r.value) }),
          h("span", { class: "mono", style: "white-space:nowrap", text: f(r.value) + (r.note ? "  " + r.note : "") })])]));
    });
    return wrap;
  };

  /* scatter({points:[{x,y,label,group,tip}], groups:[names], xLabel,yLabel,xMin,xMax,yMin,yMax}) max 3 groups */
  MB.scatter = function (o) {
    var W = 680, H = o.height || 350, m = { l: 52, r: 24, t: 34, b: 44 }, wrap = h("div", { class: "chart" });
    var X = function (v) { return m.l + (v - o.xMin) / (o.xMax - o.xMin) * (W - m.l - m.r); }, Y = function (v) { return H - m.b - (v - o.yMin) / (o.yMax - o.yMin) * (H - m.t - m.b); };
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": o.title || "scatter" });
    ticks(o.yMin, o.yMax, 5).forEach(function (t) {
      svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), stroke: "var(--grid)", "stroke-width": 1 }));
      svg.appendChild(s("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, [String(t)]));
    });
    ticks(o.xMin, o.xMax, 6).forEach(function (t) { svg.appendChild(s("text", { x: X(t), y: H - m.b + 18, "text-anchor": "middle" }, [MB.fmt.compact(t)])); });
    svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: Y(o.yMin), y2: Y(o.yMin), stroke: "var(--axis)", "stroke-width": 1 }));
    svg.appendChild(s("text", { x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle", class: "lab" }, [o.xLabel]));
    svg.appendChild(s("text", { x: 12, y: 14, class: "lab" }, [o.yLabel]));
    wrap.appendChild(h("div", { class: "legend" }, o.groups.map(function (g, i) { return h("span", {}, [h("i", { style: "background:" + SERIES[i] + (i === 0 ? "" : ";border-radius:50%") }), g]); })));
    wrap.appendChild(svg);
    var tip = tipFor(wrap);
    o.points.forEach(function (p) {
      var gi = o.groups.indexOf(p.group), cx = X(p.x), cy = Y(p.y), col = SERIES[Math.max(0, gi)];
      var mark = gi === 0 ? s("rect", { x: cx - 6, y: cy - 6, width: 12, height: 12, rx: 3, fill: col, stroke: "var(--raise)", "stroke-width": 2 })
        : s("circle", { cx: cx, cy: cy, r: 6, fill: col, stroke: "var(--raise)", "stroke-width": 2 });
      var g = s("g", { tabindex: 0, role: "img", "aria-label": p.label + ": " + p.y + " at " + p.x + " tokens" }, [s("circle", { cx: cx, cy: cy, r: 14, fill: "transparent" }), mark]);
      if (p.show) svg.appendChild(s("text", { x: cx + (p.anchor === "end" ? -10 : 10), y: cy + (p.dy || 4), "text-anchor": p.anchor || "start", class: "lab" }, [p.label]));
      function on() { var r = svg.getBoundingClientRect(); tip.show(p.tip, cx / W * r.width, cy / H * r.height); }
      g.addEventListener("pointerenter", on); g.addEventListener("focus", on);
      g.addEventListener("pointerleave", tip.hide); g.addEventListener("blur", tip.hide);
      svg.appendChild(g);
    });
    return wrap;
  };

  // ---------- mount ----------
  function mount(el) {
    var name = el.dataset.widget, fn = registry[name];
    if (el.dataset.mounted) return;
    el.dataset.mounted = "1";
    if (!fn) { el.appendChild(h("div", { class: "w-err", text: "Interactive \"" + name + "\" is not available in this build." })); return; }
    try { fn(el, new UI(el, name)); } catch (e) {
      el.textContent = "";
      el.appendChild(h("div", { class: "w-err", text: "This interactive could not start (" + e.message + "). The text around it does not depend on it." }));
      if (window.console) console.error("widget " + name, e);
    }
  }
  MB.mountAll = function (scope) { (scope || document).querySelectorAll(".widget[data-widget]").forEach(mount); };
  document.addEventListener("DOMContentLoaded", function () { MB.mountAll(); });
})();
