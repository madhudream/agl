"""Example 5: a router-first graph. Classify, hand off to a specialist, check the reply against policy.

    classify ?billing-> billing ─┐
    classify ?bug-> bug ─────────┼──► policy_check ?ok-> END
    classify ?other-> general ───┘        ?fail-> (back to the handler that wrote the reply)

This is the "routing" and "handoff" pattern: one cheap classifier decides which specialist loop runs;
each specialist has its own system prompt and tools; a deterministic policy check runs every time and
sends a bad reply back to the specialist with the exact rule it broke. The same shape serves support
triage, intake forms, incident routing and document classification: change the labels, the
specialists and the policy.

    uv run python examples/triage.py "I was charged twice for March and the app crashes on login"
"""
import re
import sys

from agl import LLM, Graph, Loop, check, default_plugins, parse_json

LABELS = ("billing", "bug", "other")
POLICY = [
    (r"\b(refund(ed)?|credit(ed)?)\b.*\b(will|guarantee|promise)\b",
     "do not promise refunds or credits; say what will be reviewed"),
    (r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", "never include a card number"),
    (r"\b(password|api key|token)\b.*\b(is|:)\b", "never state a credential"),
    (r"!", "no exclamation marks in support replies"),
]


def policy_violations(reply: str) -> list[str]:
    return [why for pattern, why in POLICY if re.search(pattern, reply, re.I)]


def build(llm: LLM) -> Graph:
    classifier = Loop(llm, name="classify", json_mode=True, max_fails=1,
                      system='Classify a support message. Reply with JSON only: '
                             '{"kind": "billing"|"bug"|"other", "summary": "..."}',
                      evaluate=check(lambda a: parse_json(a).get("kind") in LABELS or f"kind must be one of {LABELS}"))

    def classify(s: dict) -> dict:
        data = parse_json(classifier.run(s["message"], state=s).answer)
        return {"kind": data["kind"], "summary": data.get("summary", "")}

    def specialist(name: str, system: str):
        loop = Loop(llm, name=name, max_fails=2,
                    system=system + " Reply to the customer in under 120 words. Plain language, no exclamation marks.",
                    evaluate=check(lambda a: not policy_violations(a) or "Policy: " + "; ".join(policy_violations(a))))

        def node(s: dict) -> dict:
            prev = (f"\n\nYour previous reply broke policy: {s['policy_feedback']}\nRewrite it."
                    if s.get("policy_feedback") else "")
            r = loop.run(f"Customer message:\n{s['message']}\n\nSummary: {s['summary']}{prev}", state=s)
            return {"reply": r.answer, "handler": name}

        node.kind = "loop"
        return node

    def policy_check(s: dict) -> dict:  # deterministic, runs every time, cannot be skipped by the model
        v = policy_violations(s["reply"])
        return {"policy_ok": not v, "policy_feedback": "; ".join(v)}

    return Graph.from_text("""
        START -> classify
        classify ?billing-> billing
        classify ?bug-> bug
        classify ?other-> general
        billing, bug, general -> policy_check
        policy_check ?ok-> END
        policy_check ?billing-> billing
        policy_check ?bug-> bug
        policy_check ?other-> general
    """, nodes={
        "classify": classify,
        "billing": specialist("billing", "You are a billing specialist. You can explain charges and open a review; "
                                         "you cannot issue refunds."),
        "bug": specialist("bug", "You are a support engineer. Ask for the one detail that would reproduce "
                                 "the problem."),
        "general": specialist("general", "You are a friendly generalist for a software product."),
        "policy_check": policy_check,
    }, routers={
        "classify": lambda s: s["kind"],
        "policy_check": lambda s: "ok" if s["policy_ok"] else s["handler"],
    }, name="triage")


if __name__ == "__main__":
    message = " ".join(sys.argv[1:]) or "I was charged twice for March and I want my money back now"
    state = build(LLM()).run({"message": message}, plugins=default_plugins(verbose=False))
    print(f"\nkind: {state.get('kind')}  handler: {state.get('handler')}  policy_ok: {state.get('policy_ok')}")
    print(f"path: {' → '.join(state['_path'])}\n\n{state.get('reply')}")
