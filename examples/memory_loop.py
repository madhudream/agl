"""Example 3: a loop with long-term memory.

    uv run python examples/memory_loop.py

Run it twice. The first run has nothing to recall and stores facts from the
conversation. The second run starts with a dated fact block in its system prompt
and answers from memory. The shipped backend keeps everything in one SQLite file under data/.
"""
from agl import LLM, Loop, Plugins, Toolbox, default_plugins
from agl.memory import Memory

llm = LLM()
mem = Memory(user_id="demo:memory_loop")  # recall before the run, remember after it

loop = Loop(llm, tools=Toolbox(*mem.tools), plugins=default_plugins() + Plugins(mem),
            system="You are a helpful assistant. Use recall() if memory may hold the answer; "
                   "use remember() when the user tells you something worth keeping.")

print("known facts before:", len(mem.all()))
if not mem.all():
    r = loop.run("I'm Hanu. I'm building an interactive course app in Python; my students are in Kansas City "
                 "and I prefer plain-English explanations with no em dashes. Say hi and confirm what you'll remember.")
    print("\n", r.answer)
    mem.flush()
    print("\nfacts stored:", [row["text"] for row in mem.all()])
else:
    r = loop.run("Remind me: where are my students and what writing style do I prefer? One sentence.")
    print("\n", r.answer)
    print("\nrecalled block was:\n", mem.last_block)
