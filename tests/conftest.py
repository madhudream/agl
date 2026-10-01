"""Offline test doubles: a scripted LLM so loops and graphs run without a network."""
from __future__ import annotations

import json

import pytest

from agl.llm import LLM, Meter, Reply, Usage


class FakeLLM(LLM):
    """Replays a script of replies. Each entry is a str (text) or a list of (tool_name, args) calls."""

    def __init__(self, script: list, model: str = "fake/model"):
        self.model = model
        self.script = list(script)
        self.calls: list[list[dict]] = []
        self.meter = Meter()
        self.cache = None
        self.temperature = None
        self.max_tokens = None

    def with_model(self, model):
        return self

    def chat(self, messages, *, tools=None, json_mode=False, model=None, temperature=None, max_tokens=None,
             tool_choice=None, json_schema=None) -> Reply:
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        item = self.script.pop(0)
        usage = Usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.0001, ms=1)
        if isinstance(item, str):
            return Reply(text=item, tool_calls=[], usage=usage,
                         raw_message={"role": "assistant", "content": item}, finish_reason="stop")
        calls = [{"id": f"c{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(item)]
        raw = {"role": "assistant", "content": None,
               "tool_calls": [{"id": c["id"], "type": "function",
                               "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                              for c in calls]}
        return Reply(text="", tool_calls=calls, usage=usage, raw_message=raw, finish_reason="tool_calls")


@pytest.fixture
def fake():
    return FakeLLM
