#!/usr/bin/env python3
"""Codex discovery entry; setup logic remains shared with the Claude plugin."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "scripts"))
from setup import main
from ext import EXECUTOR_ENV

if __name__ == "__main__":
    os.environ[EXECUTOR_ENV] = "codex"
    if len(sys.argv) > 1 and sys.argv[1] in ("agent", "init"):
        if not any(arg == "--agent" or arg.startswith("--agent=") for arg in sys.argv[2:]):
            sys.argv += ["--agent", "codex"]
        if sys.argv[1] == "agent" and not any(arg in ("--add", "--select") for arg in sys.argv[2:]):
            sys.argv.append("--add")
    sys.exit(main())
