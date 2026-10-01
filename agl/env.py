"""Load `.env` files into os.environ without a dependency.

Looks in the current directory and the project root (this package's parent).
Existing variables are never overwritten.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(*paths: str | Path) -> None:
    candidates = [Path(p) for p in paths] or [Path.cwd() / ".env", ROOT / ".env"]
    for p in candidates:
        if not p.is_file():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k.startswith("export "):
                k = k[7:].strip()
            os.environ.setdefault(k, v)
