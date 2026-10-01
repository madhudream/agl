"""A small standard toolbox: enough for coding-agent style tasks, nothing clever.

Every tool is a plain function; `@tool` derives the schema. Paths are confined to
`AGL_WORKDIR` (default: the current directory) so an agent cannot wander.
"""
from __future__ import annotations

import ast
import operator as op
import os
import subprocess
from pathlib import Path

from .tools import tool

WORKDIR = Path(os.environ.get("AGL_WORKDIR", ".")).resolve()


def _safe(path: str) -> Path:
    p = (WORKDIR / path).resolve()
    if not str(p).startswith(str(WORKDIR)):
        raise PermissionError(f"{path} is outside the work directory")
    return p


_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow,
        ast.Mod: op.mod, ast.FloorDiv: op.floordiv, ast.USub: op.neg}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only arithmetic is allowed")


@tool
def calc(expression: str) -> float:
    """Evaluate an arithmetic expression exactly (+ - * / ** % //). Use it instead of mental math.

    Args:
        expression: e.g. "17 * 25 + 3"
    """
    return _eval(ast.parse(expression, mode="eval").body)


@tool
def read_file(path: str, start: int = 1, end: int = 200) -> str:
    """Read lines [start, end] of a text file (1-indexed).

    Args:
        path: file path relative to the work directory
        start: first line
        end: last line
    """
    lines = _safe(path).read_text(errors="replace").splitlines()
    return "\n".join(f"{i:>5} {text}" for i, text in enumerate(lines[start - 1:end], start))


@tool
def write_file(path: str, content: str) -> str:
    """Write a whole text file (creates parent folders).

    Args:
        path: file path relative to the work directory
        content: the full new content
    """
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} chars to {path}"


@tool
def list_files(path: str = ".", pattern: str = "**/*") -> list[str]:
    """List files under a folder.

    Args:
        path: folder relative to the work directory
        pattern: glob pattern
    """
    root = _safe(path)
    return sorted(str(p.relative_to(WORKDIR)) for p in root.glob(pattern)
                  if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts)[:300]


@tool
def grep(pattern: str, path: str = ".", glob: str = "**/*.py") -> str:
    """Search files for a regex and return matching lines with file:line prefixes.

    Args:
        pattern: regular expression
        path: folder to search
        glob: which files
    """
    import re
    rx = re.compile(pattern)
    out = []
    root = _safe(path)
    files = [root] if root.is_file() else root.glob(glob)  # a file path searches just that file
    for p in files:
        if not p.is_file() or ".git" in p.parts:
            continue
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if rx.search(line):
                out.append(f"{p.relative_to(WORKDIR)}:{i}: {line.strip()[:200]}")
            if len(out) >= 200:
                return "\n".join(out) + "\n... (truncated)"
    return "\n".join(out) or "no matches"


@tool
def shell(command: str, timeout: int = 60) -> str:
    """Run a shell command in the work directory and return stdout+stderr (exit code on the last line).

    Args:
        command: the command
        timeout: seconds
    """
    r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()[-8000:] + f"\n[exit {r.returncode}]"


@tool
def read_pdf(path: str, max_chars: int = 60_000) -> str:
    """Extract the text of a PDF file.

    Args:
        path: pdf path relative to the work directory
        max_chars: cap on returned characters
    """
    from pypdf import PdfReader
    reader = PdfReader(str(_safe(path)))
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    return text[:max_chars]


STD_TOOLS = {t.name: t for t in (calc, read_file, write_file, list_files, grep, shell, read_pdf)}
