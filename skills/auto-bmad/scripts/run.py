#!/usr/bin/env python3
"""Resolve the source/plugin checkout even when the skill folder is symlinked."""

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from run_queue import main
from ext import EXECUTOR_ENV

if __name__ == "__main__":
    os.environ[EXECUTOR_ENV] = "claude"
    sys.exit(main())
