#!/usr/bin/env python3
"""Native chat helper: prepares and records work; never launches a model."""

from pathlib import Path
import os
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(root / "scripts"))
    from ext import EXECUTOR_ENV
    from native_session import main
    os.environ[EXECUTOR_ENV] = "codex"
    sys.exit(main())
