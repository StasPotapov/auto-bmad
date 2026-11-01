"""Bound an unresponsive workflow step, with a warning and a second progress check."""

import time


class InactivityWatch:
    def __init__(self, timeout, *, clock=time.monotonic):
        self.timeout, self.clock = timeout, clock
        self.last_progress = clock()
        self.confirmation = min(120, timeout)
        self.suspected_at = None
        self.evidence = {"state": "active", "idle_limit": timeout}

    def progress(self):
        self.last_progress = self.clock()
        self.suspected_at = None
        self.evidence = {"state": "active", "idle_limit": self.timeout}

    def observe(self, *, paused=False):
        if paused:
            self.progress()
            self.evidence["state"] = "waiting_for_supervised_work"
        elif self.clock() - self.last_progress >= self.timeout:
            if self.suspected_at is None:
                self.suspected_at = self.clock()
            confirmed = self.clock() - self.suspected_at >= self.confirmation
            self.evidence = {"state": "suspected_stall", "idle_limit": self.timeout,
                             "idle_seconds": round(self.clock() - self.last_progress, 3),
                             "confirmation_seconds": self.confirmation,
                             "confirmation_elapsed": round(self.clock() - self.suspected_at, 3),
                             "action": "keep_running", "reason": "no meaningful workflow events"}
            if confirmed:
                self.evidence.update(state="stalled", action="stop")
                return True
        elif self.evidence["state"] == "waiting_for_supervised_work":
            self.evidence = {"state": "active", "idle_limit": self.timeout}
        return False
