"""Read historical Codex JSONL usage; this module never launches models."""

import collections
import json
from agent_runtime import ProtocolError


class CodexResult:
    """Transport success requires both a completed turn and a structured final message."""

    def __init__(self):
        self.completed = False
        self.final = None
        self.usage = None
        self.failure = None
        self.thread = None
        self.turns = []
        self.turn_open = None
        self.tools = collections.Counter()
        self.tool_ids = set()
        self.progress_events = set()

    def consume(self, event):
        kind = event.get("type")
        if kind == "thread.started":
            self.thread = event.get("thread_id")
        elif kind == "turn.started":
            self.turn_open = True
        elif kind == "turn.completed":
            self.completed = True
            self.usage = event.get("usage")
            if self.turn_open is not False:
                usage = self.usage if isinstance(self.usage, dict) else {}
                self.turns.append({k: v for k, v in usage.items()
                                   if k in ("input_tokens", "cached_input_tokens", "output_tokens")})
            self.turn_open = False
        elif kind in ("turn.failed", "error"):
            self.failure = event.get("error") or event.get("message") or "agent failed"
        elif kind == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                raise ProtocolError("invalid item.completed")
            if item.get("type") == "agent_message":
                self.final = item.get("text")
            elif item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                identity = item.get("id")
                if identity is None or identity not in self.tool_ids:
                    self.tools[item["type"]] += 1
                    if identity is not None:
                        self.tool_ids.add(identity)
        item = event.get("item", {})
        meaningful = (kind in ("thread.started", "turn.started", "turn.completed", "turn.failed", "error") or
                      (kind in ("item.started", "item.updated", "item.completed") and isinstance(item, dict) and
                       item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search")))
        if meaningful:
            fingerprint = json.dumps({**event, "item": {k: v for k, v in item.items() if k != "id"}}
                                     if isinstance(item, dict) and kind.startswith("item.") and
                                     item.get("type") != "file_change" else event, sort_keys=True)
            if fingerprint not in self.progress_events:
                self.progress_events.add(fingerprint)
                return True
        return False

    def snapshot(self):
        return {"turns": self.turns, "unfinished_turn": self.turn_open is True or self.failure is not None,
                "tools": dict(self.tools)}

    def finish(self, exit_code):
        if self.failure is not None or exit_code:
            return {"execution_status": "failed", "error": {"kind": "process", "message": str(self.failure or
                    f"CLI exit {exit_code}")}, "resume_handle": self.thread}
        if not self.completed or not isinstance(self.final, str):
            raise ProtocolError("missing completed turn or final message")
        result = json.loads(self.final)
        if not isinstance(result, dict):
            raise ProtocolError("final result must be a JSON object")
        return {"execution_status": "completed", "result": result, "usage": self.usage,
                "resume_handle": self.thread}
