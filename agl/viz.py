"""Draw it. A graph becomes an .excalidraw file; a trace becomes a self-contained HTML page.

    agl viz graph examples/02_graph_fanout.py --excalidraw docs/fanout.excalidraw
    agl viz trace traces/run.jsonl -o traces/run.html

Students learn graph engineering by seeing waves run, so the viewer replays the
trace node by node with the state keys each one wrote and what each LLM call cost.
"""
from __future__ import annotations

import html
import json
import random
from pathlib import Path

# ── excalidraw ───────────────────────────────────────────────────────────────────────────────

_COLORS = {"fn": ("#e9ecef", "#1e1e1e"), "loop": ("#d0ebff", "#1971c2"), "graph": ("#fff3bf", "#e67700")}


def _el(kind: str, **kw) -> dict:
    base = {"id": kw.pop("id", f"{kind}-{random.randrange(10**9):09d}"), "type": kind, "angle": 0,
            "strokeColor": "#1e1e1e", "backgroundColor": "transparent", "fillStyle": "solid", "strokeWidth": 2,
            "strokeStyle": "solid", "roughness": 1, "opacity": 100, "groupIds": [], "frameId": None,
            "roundness": {"type": 3} if kind == "rectangle" else ({"type": 2} if kind == "arrow" else None),
            "seed": random.randrange(10**9), "version": 1, "versionNonce": random.randrange(10**9),
            "isDeleted": False, "boundElements": [], "updated": 1, "link": None, "locked": False}
    base.update(kw)
    return base


def _text(x, y, w, h, text, size=20, cid=None, **kw) -> dict:
    props = {"textAlign": "center", "verticalAlign": "middle", "containerId": cid, "lineHeight": 1.25,
             "autoResize": True, "fontSize": size, "fontFamily": 1, "text": text, "originalText": text, **kw}
    return _el("text", x=x, y=y, width=w, height=h, **props)


def graph_to_excalidraw(graph) -> dict:
    """Layered left-to-right layout: one column per topological layer, routers drawn as labelled arrows."""
    W, H, GX, GY = 180, 64, 120, 40
    els: list[dict] = []
    pos: dict[str, tuple[float, float]] = {}
    layers = [["START"], *graph.layers(), ["END"]]
    maxrows = max(len(col) for col in layers)
    for ci, col in enumerate(layers):
        x = ci * (W + GX)
        for ri, name in enumerate(col):
            y = (maxrows - len(col)) * (H + GY) / 2 + ri * (H + GY)
            pos[name] = (x, y)
            if name in ("START", "END"):
                e = _el("ellipse", id=f"n-{name}", x=x + W / 2 - 30, y=y + H / 2 - 30, width=60, height=60,
                        backgroundColor="#b2f2bb" if name == "START" else "#ffc9c9")
                t = _text(x + W / 2 - 30, y + H / 2 - 12, 60, 25, name, 14, cid=e["id"])
            else:
                kind = graph.nodes[name].kind
                bg, stroke = _COLORS.get(kind, _COLORS["fn"])
                e = _el("rectangle", id=f"n-{name}", x=x, y=y, width=W, height=H, backgroundColor=bg,
                        strokeColor=stroke)
                label = name if kind == "fn" else f"{name}\n({kind})"
                t = _text(x, y + H / 2 - 12, W, 25, label, 18, cid=e["id"])
            e["boundElements"] = [{"id": t["id"], "type": "text"}]
            els += [e, t]
    for e in graph.describe()["edges"]:
        (sx, sy), (dx, dy) = pos[e["src"]], pos[e["dst"]]
        x0, y0 = sx + W, sy + H / 2
        x1, y1 = dx, dy + H / 2
        if e["src"] in ("START", "END"):
            x0 -= W / 2 - 30
        if e["dst"] in ("START", "END"):
            x1 += W / 2 - 30
        back = x1 < x0
        pts = [[0, 0], [x1 - x0, y1 - y0]] if not back else \
            [[0, 0], [0, -(H / 2 + 24)], [x1 - x0 - W, -(H / 2 + 24)], [x1 - x0 - W, (y1 - y0)]]
        arrow = _el("arrow", x=x0, y=y0, width=abs(x1 - x0), height=abs(y1 - y0) or 1, points=pts,
                    endArrowhead="arrow", startArrowhead=None,
                    strokeStyle="dashed" if e["label"] else "solid",
                    strokeColor="#e8590c" if e["label"] else "#1e1e1e",
                    startBinding={"elementId": f"n-{e['src']}", "focus": 0, "gap": 4},
                    endBinding={"elementId": f"n-{e['dst']}", "focus": 0, "gap": 4})
        els.append(arrow)
        if e["label"]:
            mx, my = x0 + pts[1][0] / 2, y0 + pts[1][1] / 2 - 14
            els.append(_text(mx - 30, my - 10, 60, 20, e["label"], 14, strokeColor="#e8590c"))
    title = _text(0, -90, 600, 40, f"{graph.name}: {len(graph.nodes)} nodes, {len(graph.describe()['edges'])} edges",
                  28, textAlign="left")
    els.insert(0, title)
    return {"type": "excalidraw", "version": 2, "source": "agl", "elements": els,
            "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None}, "files": {}}


# ── trace → html ─────────────────────────────────────────────────────────────────────────────

def read_trace(path: str | Path) -> list[dict]:
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def trace_to_html(events: list[dict], title: str = "agl trace") -> str:
    """A single HTML file: graph picture (mermaid), wave timeline, and every LLM/tool event."""
    graphs = [e for e in events if e["kind"] == "graph_start"]
    mermaid = ""
    if graphs:
        g = graphs[-1]
        lines = ["flowchart LR", "  START(( ))", "  END(( ))"]
        lines += [f"  {n}[{n}]" for n in g["nodes"]]
        for e in g["edges"]:
            lines.append(f"  {e['src']} {'-- ' + e['label'] + ' -->' if e.get('label') else '-->'} {e['dst']}")
        mermaid = "\n".join(lines)
    cost = sum(e.get("cost_usd", 0) or 0 for e in events if e["kind"] == "llm")
    calls = sum(1 for e in events if e["kind"] == "llm")
    tools = sum(1 for e in events if e["kind"] == "tool")
    data = json.dumps(events).replace("</", "<\\/")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<style>
:root{{--bg:#fff;--fg:#1e1e1e;--mut:#6b7280;--card:#f6f7f9;--line:#e5e7eb;--acc:#1971c2;--ok:#2b8a3e;--bad:#c92a2a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1115;--fg:#e8eaed;--mut:#9aa0a6;--card:#171a21;--line:#2a2f3a;--acc:#74c0fc}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin-inline:auto}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:var(--mut);margin-bottom:16px}}
.tiles{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}} .tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:120px}}
.tile b{{display:block;font-size:20px}} .tile span{{color:var(--mut);font-size:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0;overflow:auto}}
.ev{{border-left:3px solid var(--line);padding:6px 10px;margin:6px 0;font-size:14px}} .ev.llm{{border-color:var(--acc)}} .ev.tool{{border-color:#f59f00}}
.ev.node_end{{border-color:var(--ok)}} .ev.evaluate.fail{{border-color:var(--bad)}} .ev.route{{border-color:#e8590c}}
.k{{color:var(--mut);font-size:12px}} pre{{white-space:pre-wrap;margin:4px 0;font-size:13px}}
.wave{{display:inline-block;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px;margin:4px}}
button{{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer}}
</style></head><body>
<h1>{html.escape(title)}</h1><div class="sub">{len(events)} events</div>
<div class="tiles"><div class="tile"><b>{calls}</b><span>LLM calls</span></div><div class="tile"><b>{tools}</b><span>tool calls</span></div>
<div class="tile"><b>${cost:.4f}</b><span>cost</span></div></div>
{'<div class="card"><pre class="mermaid">' + html.escape(mermaid) + '</pre></div>' if mermaid else ''}
<div class="card"><button id="play">▶ replay</button> <span id="waves"></span></div>
<div id="events"></div>
<script>
const EV = {data};
if (window.mermaid) mermaid.initialize({{startOnLoad:true, theme: matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'default'}});
const box = document.getElementById('events');
function esc(s){{return String(s??'').replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}
function render(e){{
  const d = document.createElement('div'); d.className = 'ev ' + e.kind + (e.kind==='evaluate' ? (e.passed?' pass':' fail') : '');
  let body = '';
  if (e.kind==='llm') body = `<div class="k">step ${{e.step}} · ${{e.ms}}ms · ${{e.prompt_tokens}}+${{e.completion_tokens}} tok · $${{(e.cost_usd||0).toFixed(5)}}</div>` +
     (e.tool_calls?.length ? `<pre>→ ${{esc(e.tool_calls.map(c=>c.name+'('+JSON.stringify(c.arguments)+')').join(', '))}}</pre>` : `<pre>${{esc(e.text)}}</pre>`);
  else if (e.kind==='tool') body = `<div class="k">tool ${{esc(e.name)}} ${{esc(JSON.stringify(e.arguments))}}</div><pre>${{esc(e.result)}}</pre>`;
  else if (e.kind==='evaluate') body = `<div class="k">evaluate</div><pre>${{e.passed?'PASS':'FAIL'}} ${{esc(e.feedback||'')}} ${{e.score!=null?'score='+e.score:''}}</pre>`;
  else if (e.kind==='node_start') body = `<div class="k">node start</div><b>▶ ${{esc(e.node)}}</b>`;
  else if (e.kind==='node_end') body = `<div class="k">node end · ${{e.ms}}ms</div><b>■ ${{esc(e.node)}}</b> wrote ${{esc((e.keys||[]).join(', '))}} ${{e.error?'<span style="color:var(--bad)">'+esc(e.error)+'</span>':''}}`;
  else if (e.kind==='route') body = `<div class="k">route</div>${{esc(e.router)}} --${{esc(e.label)}}--> ${{esc(e.target)}}`;
  else if (e.kind==='run_start') body = `<div class="k">loop ${{esc(e.name)}} · ${{esc(e.model)}}</div><pre>${{esc(e.task)}}</pre>`;
  else if (e.kind==='run_end') body = `<div class="k">loop end · ${{e.status}} · ${{e.steps}} steps · ${{e.ms}}ms · $${{(e.cost_usd||0).toFixed(5)}}</div><pre>${{esc(e.answer)}}</pre>`;
  else if (e.kind==='graph_end') body = `<div class="k">graph end</div>path: ${{esc((e.path||[]).join(' → '))}}`;
  else if (e.kind==='graph_start') body = `<div class="k">graph start</div><b>${{esc(e.graph)}}</b>: ${{(e.nodes||[]).length}} nodes, ${{(e.edges||[]).length}} edges`;
  else body = `<div class="k">${{esc(e.kind)}}</div><pre>${{esc(JSON.stringify(e))}}</pre>`;
  d.innerHTML = body; return d;
}}
EV.forEach(e => box.appendChild(render(e)));
// waves: consecutive node_start events form one wave
const waves = []; let cur = null;
for (const e of EV) {{ if (e.kind==='node_start') {{ if (!cur) {{cur=[]; waves.push(cur);}} cur.push(e.node);}} else if (e.kind!=='node_start' && cur && e.kind==='node_end') {{ /* keep wave open until next non-node event */ }} else cur=null; }}
document.getElementById('waves').innerHTML = waves.map((w,i)=>`<span class="wave">wave ${{i+1}}: ${{esc(w.join(' ∥ '))}}</span>`).join('');
document.getElementById('play').onclick = async () => {{
  box.innerHTML=''; for (const e of EV) {{ box.appendChild(render(e)); window.scrollTo(0, document.body.scrollHeight); await new Promise(r=>setTimeout(r, e.kind==='llm'?350:120)); }}
}};
</script></body></html>"""
