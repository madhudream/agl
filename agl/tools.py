"""Tools: a Python function becomes a tool the model can call.

    @tool
    def read_file(path: str) -> str:
        \"\"\"Read a text file.\"\"\"
        return open(path).read()

The JSON schema is derived from the signature and the docstring, so a tool is
defined exactly once (DRY). `Toolbox` holds a set of tools and executes calls.
"""
from __future__ import annotations

import inspect
import json
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def _schema_for(annotation: Any) -> dict:
    origin = typing.get_origin(annotation)
    if origin is list:
        (inner,) = typing.get_args(annotation) or (str,)
        return {"type": "array", "items": _schema_for(inner)}
    if origin is typing.Literal:
        return {"type": "string", "enum": list(typing.get_args(annotation))}
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _schema_for(args[0]) if len(args) == 1 else {}
    return {"type": _JSON_TYPES.get(annotation, "string")}


def _param_docs(doc: str) -> dict[str, str]:
    """Parse `name: description` lines from an Args:/Parameters: block."""
    out: dict[str, str] = {}
    active = False
    for line in doc.splitlines():
        s = line.strip()
        if s.lower().rstrip(":") in ("args", "arguments", "parameters", "params"):
            active = True
            continue
        if active and s and ":" in s and not s.startswith(("Returns", "Raises")):
            name, desc = s.split(":", 1)
            out[name.split("(")[0].strip()] = desc.strip()
        elif active and not s:
            active = False
    return out


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]

    @property
    def spec(self) -> dict:
        """OpenAI tools[] entry."""
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}

    def __call__(self, **kwargs) -> Any:
        return self.fn(**kwargs)


def tool(fn: Callable | None = None, *, name: str | None = None, description: str | None = None) -> Any:
    """Decorator: turn a typed function into a Tool."""

    def wrap(f: Callable) -> Tool:
        doc = inspect.getdoc(f) or ""
        param_docs = _param_docs(doc)
        hints = typing.get_type_hints(f)
        props, required = {}, []
        for p in inspect.signature(f).parameters.values():
            if p.name.startswith("_") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            schema = _schema_for(hints.get(p.name, str))
            if p.name in param_docs:
                schema["description"] = param_docs[p.name]
            props[p.name] = schema
            if p.default is p.empty:
                required.append(p.name)
        params = {"type": "object", "properties": props, "required": required}
        return Tool(name=name or f.__name__, description=description or doc.split("\n\n")[0].strip() or f.__name__,
                    parameters=params, fn=f)

    return wrap(fn) if fn else wrap


def to_text(result: Any, limit: int = 12_000) -> str:
    """Tool results travel back to the model as text; keep them bounded."""
    s = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + f"\n... [truncated {len(s) - limit} chars]"


@dataclass
class Toolbox:
    tools: dict[str, Tool] = field(default_factory=dict)

    def __init__(self, *tools: Tool | Callable):
        self.tools = {}
        for t in tools:
            self.add(t)

    def add(self, t: Tool | Callable) -> Toolbox:
        t = t if isinstance(t, Tool) else tool(t)
        self.tools[t.name] = t
        return self

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def __len__(self) -> int:
        return len(self.tools)

    @property
    def specs(self) -> list[dict]:
        return [t.spec for t in self.tools.values()]

    def call(self, name: str, arguments: dict) -> str:
        """Execute one tool call; errors come back as text, never raised (the model must see them)."""
        if name not in self.tools:
            return f"error: unknown tool '{name}'. Available: {', '.join(self.tools)}"
        try:
            return to_text(self.tools[name](**arguments))
        except TypeError as exc:
            return f"error: bad arguments for {name}: {exc}"
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"
