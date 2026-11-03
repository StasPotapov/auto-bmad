#!/usr/bin/env python3
"""Read-only native Claude planning entry; execution belongs to the chat skill."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from native_session import main
from ext import EXECUTOR_ENV

if __name__ == "__main__":
    os.environ[EXECUTOR_ENV] = "claude"
    if len(sys.argv) < 2 or sys.argv[1] != "plan":
        sys.exit("Use the native Claude auto-bmad skill to execute; this helper only plans.")
    sys.exit(main())
