#!/usr/bin/env python3
"""Provider-specific discovery wrapper; all execution stays in the shared CLI."""

from pathlib import Path
import os
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(root / "scripts"))
    from ext import EXECUTOR_ENV
    from run_queue import main
    os.environ[EXECUTOR_ENV] = "codex"
    sys.exit(main())
