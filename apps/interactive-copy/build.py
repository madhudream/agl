#!/usr/bin/env python3
"""Shortcut: python3 build.py [--check] == python3 engine/build.py [--check]"""
import runpy, sys
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent / "engine" / "build.py"), run_name="__main__")
