"""Is an MCP server added and logged in — asked through `claude mcp get`, which runs its health check.

The Claude Design server (`claude_design`) has its own login: without it the mockmatch check
cannot pull a design from Claude Design.
"""

import re
import shutil
import subprocess

CLAUDE_DESIGN = "claude_design"
CLAUDE_DESIGN_URL = "https://api.anthropic.com/v1/design/mcp"


def parse_status(name, code, text):
    """`claude mcp get` output → {"state", "message"}.

    state: connected | auth (added, not logged in) | missing (not added) | failed."""
    login = f"log in: in Claude Code /mcp → {name} → Authenticate"
    if code != 0 and re.search(r"No MCP server", text, re.I):
        add = (f"claude mcp add --transport http -s user {name} {CLAUDE_DESIGN_URL}"
               if name == CLAUDE_DESIGN else f"claude mcp add … {name}")
        return {"state": "missing", "message": f"MCP {name} is not added — run `{add}`, then {login}"}
    status = next((ln.split(":", 1)[1].strip() for ln in text.splitlines()
                   if ln.strip().lower().startswith("status:")), "")
    if re.search(r"\bconnected\b", status, re.I) and not re.search(r"not|fail", status, re.I):
        return {"state": "connected", "message": f"MCP {name} is connected"}
    if re.search(r"auth|login|token|401|403", status + text, re.I):
        return {"state": "auth",
                "message": f"MCP {name} is not logged in ({status or 'needs authentication'}) — {login}"}
    return {"state": "failed",
            "message": f"MCP {name}: {status or 'unknown status'} — check the network, then {login}"}


def status(name=CLAUDE_DESIGN, timeout=60):
    exe = shutil.which("claude")
    if not exe:
        return {"state": "unknown", "message": "the claude CLI is not in PATH — cannot check MCP " + name}
    try:
        proc = subprocess.run([exe, "mcp", "get", name], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"state": "unknown", "message": f"claude mcp get {name} failed: {e}"}
    return parse_status(name, proc.returncode, proc.stdout + proc.stderr)
