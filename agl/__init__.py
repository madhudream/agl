"""agl: Agentic Graph Loop.

    from agl import LLM, Loop, Graph, Toolbox, tool, judge, check, default_plugins

Five files carry the idea: llm.py (one measured client), tools.py (function → tool),
loop.py (the agent loop), graph.py (loops composed into a graph), plugins.py (hooks).
memory.py adds memory (mem lib); eval.py scores runs; viz.py draws them.
"""
from .graph import END, START, Graph, Node, StateCollision, fanout
from .llm import JUDGE_MODEL, LLM, METER, SMART_MODEL, BudgetExceeded, Reply, parse_json
from .loop import Loop, Result, Run, ToolDenied, all_of, check, judge
from .plugins import Approval, Budget, Compact, Console, Plugins, Skills, Trace, default_plugins
from .tools import Tool, Toolbox, tool

__all__ = [
           "END",
           "JUDGE_MODEL",
           "LLM",
           "METER",
           "SMART_MODEL",
           "START",
           "Approval",
           "Budget",
           "Compact",
           "BudgetExceeded",
           "Console",
           "Graph",
           "Loop",
           "Node",
           "Plugins",
           "Reply",
           "Result",
           "Run",
           "Skills",
           "StateCollision",
           "Tool",
           "ToolDenied",
           "Toolbox",
           "Trace",
           "all_of",
           "check",
           "default_plugins",
           "fanout",
           "judge",
           "parse_json",
           "tool",
]
__version__ = "0.1.0"
