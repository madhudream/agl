"""Example 1: the loop. Prompt → LLM → Action → Result → Evaluate → Final Answer.

    uv run python examples/loop_hello.py

The model gets a calculator and a file reader. We evaluate the answer with a
deterministic check (it must be a bare number). Watch the Console plugin print
every step; the Trace plugin writes traces/run.jsonl for `agl viz`.
"""
from agl import LLM, Loop, Toolbox, check, default_plugins
from agl.std_tools import calc, read_file

llm = LLM()  # the worker model from AGL_MODEL

loop = Loop(
    llm,
    tools=Toolbox(calc, read_file),
    evaluate=check(lambda a: a.strip().replace(",", "").isdigit() or "reply with only the number"),
    plugins=default_plugins(),
)

result = loop.run("How many lines does agl/loop.py have, multiplied by 7? Reply with only the number.")
print("\nanswer:", result.answer, "| passed:", result.passed, "| usage:", result.run.usage())
