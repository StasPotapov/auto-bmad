#!/usr/bin/env python3
"""Provider-specific discovery wrapper; all execution stays in the shared CLI."""

from pathlib import Path
import runpy

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[5]
    runpy.run_path(str(root / "skills/auto-bmad/scripts/run.py"), run_name="__main__")
