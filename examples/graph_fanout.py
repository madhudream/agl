"""Example 2: the graph from the whiteboard.

    Prompt → plan ──► write_a ─┐
                  ├► write_b ─┼──► edit ──► review ──► Final
                  └► write_c ─┘      ▲          │ fail
                                     └──────────┘

Three writer loops run in the same wave, in parallel, each on one angle of the
topic. An editor stitches the drafts into one article. A reviewer (LLM judge)
passes it or routes back to the editor with feedback. The graph is drawn as text.

Lesson learned on the first run (see README): without the `edit` node the reviewer
failed three times in a row, because three writers who never see each other can
not produce "one coherent article". The graph shape is the fix, not a better prompt.

    uv run python examples/graph_fanout.py "why agents need evals"
    agl draw examples/graph_fanout.py --excalidraw docs/fanout.excalidraw
"""
import sys

from agl import JUDGE_MODEL, LLM, Graph, Loop, Plugins, Skills, default_plugins, judge, parse_json
from agl.loop import Run

ANGLES = ["a", "b", "c"]
RUBRIC = ("Reads as one coherent article for students: a clear thread from paragraph to paragraph, at least one "
          "concrete example, no repeated points, no invented statistics or citations. Judge the whole; do not fail "
          "it for having more than one example.")


def build(llm: LLM) -> Graph:
    skills = Plugins(Skills(only=["plain-writing"]))
    plan = Loop(llm, name="plan", json_mode=True,
                system="You are an editor planning a short article. Reply with JSON only.")

    def plan_node(s: dict) -> dict:
        r = plan.run(f"Topic: {s['topic']}\nGive three distinct angles for a 3-paragraph article. "
                     'JSON: {"angles": ["...", "...", "..."], "audience": "..."}', state=s)
        data = parse_json(r.answer)
        return {"angles": data["angles"][:3], "audience": data.get("audience", "students")}

    writers = {
        f"write_{tag}": Loop(llm, name=f"write_{tag}", plugins=skills,
                             system="You write one tight paragraph (80-120 words) for students. No headings.")
        .as_node(lambda s, i=i: f"Topic: {s['topic']}\nAngle: {s['angles'][i]}\nAudience: {s['audience']}",
                 key=f"para_{tag}")
        for i, tag in enumerate(ANGLES)
    }

    editor = Loop(llm, name="edit", plugins=skills,
                  system="You are an editor. Merge the drafts into one article of three short paragraphs. "
                         "Keep the best material, remove repetition, add transitions. Output the article only.")

    def edit_node(s: dict) -> dict:
        drafts = "\n\n".join(f"Draft {t.upper()}:\n{s[f'para_{t}']}" for t in ANGLES)
        prev = (f"\n\nYour previous version:\n{s['final']}\n\nReviewer feedback: {s['feedback']}"
                if s.get("feedback") else "")
        r = editor.run(f"Topic: {s['topic']}\nAudience: {s['audience']}\n\n{drafts}{prev}", state=s)
        return {"final": r.answer}

    reviewer = judge(llm, RUBRIC, threshold=0.75, model=JUDGE_MODEL)  # the judge is a different model: the exam

    def review(s: dict) -> dict:
        v = reviewer(s["final"], Run(name="review", task=s["topic"], model=JUDGE_MODEL))
        s["_emit"]("evaluate", **v)
        return {"ok": v["passed"], "feedback": v["feedback"], "score": v.get("score")}

    return Graph.from_text("""
        START -> plan
        plan -> write_a, write_b, write_c
        write_a, write_b, write_c -> edit
        edit -> review
        review ?pass-> END
        review ?fail-> edit
    """, nodes={"plan": plan_node, **writers, "edit": edit_node, "review": review},
         routers={"review": lambda s: "pass" if s["ok"] else "fail"}, name="fanout-edit-review")


if __name__ == "__main__":
    topic = " ".join(sys.argv[1:]) or "why agents need evals"
    state = build(LLM()).run({"topic": topic}, plugins=default_plugins())
    print("\n" + state["final"])
    print(f"\npath: {' → '.join(state['_path'])}  score={state.get('score')}  errors={state['errors']}")
