#!/usr/bin/env python3
"""Before the run: can the mockmatch check get the design.

stdin — the check's fields from the config (JSON); the command runs from the project root.
`design_artifact` (a claude.ai Design artifact): `claude -p` has no Artifact tool, so the check
needs the saved copy `design` — missing, exit 2. Without `design_project` there is nothing
more to check: exit 0, no output. With it, the
`claude_design` MCP must be logged in, otherwise the verifier cannot pull the design:
  exit 0 — connected;
  exit 1 — a warning: could not ask (no `claude` CLI), or not connected but `design` names
           a saved copy in the repository: the check compares with it, and it may be stale;
  exit 2 — not connected and no saved copy: the design check cannot run (blocking).
The message for the human is on stdout, one line.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
from mcp_status import CLAUDE_DESIGN, status  # noqa: E402


def main():
    try:
        fields = json.load(sys.stdin)
    except ValueError:
        fields = {}
    copy = fields.get("design")
    if fields.get("design_artifact") and not (copy and os.path.exists(copy)):
        print("design_artifact is set, but there is no saved copy (design): an unattended run cannot "
              "read artifacts. In a session ask the agent to import the artifact with mockmatch "
              "(Artifact read + mockmatch import), commit design/ and set design")
        return 2
    if not fields.get("design_project"):
        return 0
    st = status(CLAUDE_DESIGN)
    if st["state"] == "connected":
        return 0
    if st["state"] == "unknown":                 # could not ask: do not stop the run on a guess
        print(f"{st['message']}. The design check finds out itself whether Claude Design is logged in")
        return 1
    if copy and os.path.exists(copy):
        print(f"{st['message']}. The design check compares with the saved copy {copy}, "
              "it may be older than the design in Claude Design")
        return 1
    print(f"{st['message']}. The design check has no design: design_project is set, "
          "and there is no saved copy (design)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
