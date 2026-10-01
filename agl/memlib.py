"""mem lib: the small memory library shipped with agl.

One SQLite file. Facts are short dated sentences scoped to a user. Writing extracts facts from a
conversation with one model call; reading ranks facts by keyword match and recency and packs them into
a prompt block under a token budget. Enough to teach memory and to run a real assistant; swap in a
bigger framework through `agl.memory.MemoryBackend` when you need more.

    lib = MemLib(llm, path="data/memory.sqlite")
    lib.remember(messages, user_id="priya")           # extract + store (synchronous here; the plugin runs it async)
    block, n = lib.recall("where do my students live", user_id="priya", budget_tokens=800)
"""
from __future__ import annotations

import re
import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date
from pathlib import Path

from .llm import LLM, parse_json

EXTRACT_PROMPT = (
    "You extract durable facts about the user from a conversation: preferences, projects, people, places, "
    "decisions, dates. One short self-contained sentence each, names and dates spelled out. Skip small talk, "
    "one-off requests, secrets and anything the user asked you not to remember. Reply with JSON only: "
    '{"facts": ["...", "..."]} (an empty list is fine).'
)


class MemLib:
    def __init__(self, llm: LLM | None = None, path: str | Path = "data/memory.sqlite", model: str | None = None):
        self.llm = llm
        self.model = model
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._pending: list[Future] = []
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, user_id TEXT, text TEXT, "
                      "kind TEXT, day TEXT, session TEXT, UNIQUE(user_id, text))")
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(text, content='facts', "
                      "content_rowid='id')")
            c.execute("CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN "
                      "INSERT INTO facts_fts(rowid, text) VALUES (new.id, new.text); END")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=30)

    # ── write ────────────────────────────────────────────────────────────────────────────────
    def add_fact(self, fact: str, user_id: str, kind: str = "fact", session: str = "") -> bool:
        """Store one sentence as given. Returns False if the same sentence is already stored."""
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO facts(user_id, text, kind, day, session) VALUES (?,?,?,?,?)",
                            (user_id, fact.strip(), kind, date.today().isoformat(), session))
            return cur.rowcount == 1

    def extract(self, messages: list[dict]) -> list[str]:
        """One model call: the conversation in, a list of fact sentences out."""
        if self.llm is None:
            return []
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages if m.get("content"))
        reply = self.llm.chat([{"role": "system", "content": EXTRACT_PROMPT},
                               {"role": "user", "content": transcript[:12000]}], json_mode=True, model=self.model,
                              temperature=0)
        try:
            facts = parse_json(reply.text).get("facts", [])
        except (ValueError, AttributeError):
            return []
        return [str(f).strip() for f in facts if str(f).strip()]

    def remember(self, messages: list[dict], user_id: str, session: str = "") -> int:
        """Extract and store. Returns how many new facts were kept."""
        return sum(self.add_fact(f, user_id, "fact", session) for f in self.extract(messages))

    def remember_async(self, messages: list[dict], user_id: str, session: str = "") -> Future:
        fut = self._pool.submit(self.remember, messages, user_id, session)
        self._pending.append(fut)
        return fut

    def flush(self) -> None:
        for f in self._pending:
            f.result()
        self._pending.clear()

    # ── read ─────────────────────────────────────────────────────────────────────────────────
    def search(self, query: str, user_id: str, k: int = 10) -> list[dict]:
        """Keyword search (FTS5, BM25 order), newest first among ties. Falls back to recent facts."""
        words = [w for w in re.findall(r"[A-Za-z0-9]+", query) if len(w) > 2]
        rows: list[tuple] = []
        with self._conn() as c:
            if words:
                match = " OR ".join(f'"{w}"' for w in words)
                rows = c.execute("SELECT f.text, f.day, f.kind FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
                                 "WHERE facts_fts MATCH ? AND f.user_id = ? "
                                 "ORDER BY bm25(facts_fts), f.id DESC LIMIT ?", (match, user_id, k)).fetchall()
            if not rows:
                rows = c.execute("SELECT text, day, kind FROM facts WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                                 (user_id, k)).fetchall()
        return [{"text": t, "date": d, "kind": kd} for t, d, kd in rows]

    def recall(self, query: str, user_id: str, budget_tokens: int = 800) -> tuple[str, int]:
        """A dated block of the best-matching facts that fits the budget (about 4 characters per token)."""
        lines, used = [], 0
        for r in self.search(query, user_id, k=50):
            line = f"({r['date']}) {r['text']}"
            if used + len(line) // 4 > budget_tokens:
                break
            lines.append(line)
            used += len(line) // 4
        return "\n".join(lines), len(lines)

    def facts(self, user_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT text, day, kind FROM facts WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
        return [{"text": t, "date": d, "kind": kd} for t, d, kd in rows]

    def forget_user(self, user_id: str) -> int:
        with self._lock, self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM facts WHERE user_id = ?", (user_id,))]
            for i in ids:
                c.execute("DELETE FROM facts_fts WHERE rowid = ?", (i,))
            c.execute("DELETE FROM facts WHERE user_id = ?", (user_id,))
        return len(ids)
