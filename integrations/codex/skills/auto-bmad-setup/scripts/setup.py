#!/usr/bin/env python3
"""Codex discovery entry; setup logic remains shared with the Claude plugin."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "scripts"))
from setup import main

if __name__ == "__main__":
    sys.exit(main())
