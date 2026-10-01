"""Memory: a memory framework in the loop, as a plugin and as tools.

    mem = Memory(user_id="priya:course-app")
    loop = Loop(llm, plugins=Plugins(mem), tools=Toolbox(*mem.tools))

Three effects, each optional:
  recall    before the run, the task is searched and a dated fact block is added to the system prompt
  remember  after a run that passed, the task and the answer are handed to the framework (async)
  tools     `recall(query)` and `remember(fact)` so the model can do both explicitly

Every fact is scoped to `user_id`; use "user:project" for per-project memory.

The framework behind it is a `MemoryBackend`: six methods. agl ships mem lib (`agl/memlib.py`), a small
one. Any memory framework that can store a conversation and search facts (mem0, for example) can be
wrapped in about thirty lines and passed as `backend=`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from .tools import Tool, tool


class MemoryBackend(Protocol):
    """What a memory framework must do for the loop."""

    def recall(self, query: str, user_id: str, budget_tokens: int) -> tuple[str, int]:
        """A dated fact block for the prompt (at most budget_tokens) and how many facts it holds."""

    def remember(self, messages: list[dict], user_id: str, session_id: str) -> None:
        """Extract and store what is worth keeping from a conversation. May run in the background."""

    def add_fact(self, fact: str, user_id: str) -> str:
        """Store one explicit fact as given; return a short confirmation."""

    def search(self, query: str, user_id: str, k: int) -> list[dict]:
        """Matching facts as [{"text", "date", "kind"}]."""

    def facts(self, user_id: str) -> list[dict]:
        """Every current fact for the user."""

    def flush(self) -> None:
        """Wait for background writes."""


class DefaultBackend:
    """The shipped backend: mem lib (agl/memlib.py). One SQLite file, dated facts, keyword search."""

    def __init__(self, llm=None, *, db_path: str | Path | None = None, model: str | None = None):
        from .llm import LLM
        from .memlib import MemLib

        data = Path(os.environ.get("AGL_DATA", "data"))
        self.lib = MemLib(llm or LLM(), path=db_path or data / "memory.sqlite",
                          model=model or os.environ.get("AGL_MEMORY_MODEL"))

    def recall(self, query, user_id, budget_tokens):
        return self.lib.recall(query, user_id, budget_tokens)

    def remember(self, messages, user_id, session_id):
        self.lib.remember_async(messages, user_id, session_id)

    def add_fact(self, fact, user_id):
        return "stored" if self.lib.add_fact(fact, user_id) else "already known"

    def search(self, query, user_id, k):
        return self.lib.search(query, user_id, k)

    def facts(self, user_id):
        return self.lib.facts(user_id)

    def flush(self):
        self.lib.flush()


class Memory:
    """The plugin. Hooks: system_prompt (recall), on_run_end (remember). Tools: recall, remember."""

    def __init__(self, user_id: str, *, backend: MemoryBackend | None = None, recall: bool = True,
                 remember: bool = True, budget_tokens: int = 1500, **backend_kwargs: Any):
        self.backend: MemoryBackend = backend or DefaultBackend(**backend_kwargs)
        self.user_id = user_id
        self.recall_enabled = recall
        self.remember_enabled = remember
        self.budget_tokens = budget_tokens
        self.last_block = ""
        self.tools: list[Tool] = [self._recall_tool(), self._remember_tool()]

    # ── plugin hooks ─────────────────────────────────────────────────────────────────────────
    def system_prompt(self, run) -> str | None:
        if not self.recall_enabled:
            return None
        block, n = self.backend.recall(run.task, self.user_id, self.budget_tokens)
        self.last_block = block
        if not n:
            return None
        return ("# Memory\nKnown facts about this user and their work, each with the date it was true. "
                "Use them when relevant; do not repeat them back unprompted.\n" + block)

    def on_run_end(self, run, answer) -> None:
        if not self.remember_enabled or run.status != "pass" or not answer:
            return
        self.backend.remember([{"role": "user", "content": run.task}, {"role": "assistant", "content": str(answer)}],
                              self.user_id, run.id)

    def flush(self) -> None:
        self.backend.flush()

    # ── tools ────────────────────────────────────────────────────────────────────────────────
    def _recall_tool(self) -> Tool:
        backend, uid = self.backend, self.user_id

        @tool
        def recall(query: str, k: int = 8) -> list[dict]:
            """Search long-term memory for facts about the user, their projects and past work.

            Args:
                query: what to look for, in plain words
                k: how many facts to return
            """
            return backend.search(query, uid, k)

        return recall

    def _remember_tool(self) -> Tool:
        backend, uid = self.backend, self.user_id

        @tool
        def remember(fact: str) -> str:
            """Store one self-contained fact in long-term memory (a preference, a decision, a result).

            Args:
                fact: the fact as a full sentence with names and dates spelled out
            """
            return backend.add_fact(fact, uid)

        return remember

    # ── direct access ────────────────────────────────────────────────────────────────────────
    def search(self, query: str, k: int = 10) -> list[dict]:
        return self.backend.search(query, self.user_id, k)

    def all(self) -> list[dict]:
        return self.backend.facts(self.user_id)
