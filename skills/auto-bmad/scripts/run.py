#!/usr/bin/env python3
"""Resolve the source/plugin checkout even when the skill folder is symlinked."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from run_queue import main

if __name__ == "__main__":
    sys.exit(main())
