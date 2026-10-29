#!/usr/bin/env python3
"""auto-bmad run statistics: time, tokens by role and model, tool calls,
review passes and findings — per story, stored in the project directory.

The sources are host-owned CLI usage journals and native Claude Code transcripts:
  ~/.claude/projects/<project>/<session>.jsonl              — the orchestrator;
  ~/.claude/projects/<project>/<session>/subagents/agent-*.jsonl + .meta.json
                                                            — subagents of any depth.
`.meta.json` gives the agent type and the `toolUseId` of the parent call: with it the
subagent tree is traced up to story-runner, and story-runner up to the orchestrator prompt
with the line "Story: N.M" (or "Task: <ref>" with "Spec slug: <slug>"). Review passes and
findings come from "## Review Triage Log" of the spec that story-runner named in its header.

Only anonymous data is stored: story id, level, status, time, counters, tokens, tool names
and agent types. No prompt texts, code, paths or finding texts.
The file is <repo>/.auto-bmad/stats/runs.jsonl of the main tree (a run worktree records there too), one line per story run (and one line per
session for the orchestrator); the directory is in .git/info/exclude. Recording the same
session again replaces its lines instead of duplicating them.

Usage:
    stats.py record --session <id-or-CLI-session.json> [--repo .]
    stats.py backfill [--repo .]                # past sessions of the project not recorded yet
    stats.py show [--epic N] [--last N] [--calls] [--json] [--repo .]

Exit 0 — done, 1 — call error, 2 — nothing to record or show.
"""

import argparse
import collections
import datetime
import fcntl
import glob
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from common import ARTIFACTS, main_tree, norm_num

from gitexclude import ensure_excluded

STATS = os.path.join(".auto-bmad", "stats", "runs.jsonl")
STORY_RE = re.compile(r"^Story:\s*(\d+)\.(\d+[a-z]?)(?!\w)", re.M | re.I)
TASK_RE = re.compile(r"^Task:\s*(\S+)", re.M)
SLUG_RE = re.compile(r"^Spec slug:\s*([\w.-]+)", re.M)
STORY_SLUG_RE = re.compile(r"^Story:\s*([A-Za-z][\w.-]*)", re.M)  # a check of a task: `Story: <slug> — …`
LEVEL_RE = re.compile(r"^Run level:\s*(\w+)", re.M)
NO = ("no", "none")
HEAD_RE = {k: re.compile(rf"^{k}:\s*(.+?)\s*$", re.M)
           for k in ("STATUS", "SPEC", "COMMIT", "FILES", "PASSES", "FOLLOWUP_OPEN", "DEFERRED")}
VERDICTS_RE = re.compile(r"^- verdicts:\s*(\d+) findings?(.*)$", re.M)
VERDICT_ITEM = re.compile(r"(high|medium|low|maybe-false|false)\s+(\d+)", re.I)
# A triage row: `[verdict]` `[route]` and the summary. Models drop the brackets (then only
# the template's words are taken) or the route at times. The layer is optional free text in
# front of the summary: `(blind)`, `(edge, claim)`, `Blind:`, `Edge (claim):`, `Intent D1:`;
# only the names of BMad's review layers count, so `Note:` or `Race:` is not a layer. The
# bmad-triager rows carry the layer id and the finding number: `blind-hunter #1:`.
LAYERS = r"blind|edge|intent|verification|gap|acceptance"
# The rest of a full layer id of the engine (customize.toml), after its first word.
LAYER_IDS = (r"(?<=blind)-hunter|(?<=edge)-case-hunter|(?<=intent)-alignment|(?<=verification)-gap"
             r"|(?<=acceptance)-auditor")
FINDING_RE = re.compile(r"^\s*- `(?:\[([\w-]+)\]|(high|medium|low|maybe-false|false))`[ \t]*"
                        r"(?:`(?:\[([\w-]+)\]|(intent_gap|bad_spec|patch|defer|reject))`)?[ \t]*"
                        rf"(?:\(?({LAYERS})(?:{LAYER_IDS})?\b(?=[,)]|:|[ \t]*\(|[ \t]+\w+:|[ \t]+hunter\b|[ \t]+#\d))?",
                        re.M | re.I)
REPORT_RE = re.compile(r"^(STATUS|VERDICT):", re.M)
# output_tokens in the transcript is written at the start of a reply and is far too low,
# so output is estimated from visible text and tool inputs (out_est), without reasoning.
# Input and cache are exact.
TOKEN_KEYS = (("input_tokens", "in"), ("cache_read_input_tokens", "cache_read"),
              ("cache_creation_input_tokens", "cache_write"))
CHARS_PER_TOKEN = 3.5
ZERO = ("in", "out_est", "cache_read", "cache_write")


def projects_dir():
    root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(root, "projects")


def project_key(repo):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(repo))


def session_files(repo):
    """Project sessions: {session_id: path to the orchestrator .jsonl}."""
    out = {}
    for path in glob.glob(os.path.join(projects_dir(), project_key(repo), "*.jsonl")):
        out[os.path.basename(path)[:-6]] = path
    return out


def find_session(repo, sid):
    path = session_files(repo).get(sid)
    if path:
        return path
    hits = glob.glob(os.path.join(projects_dir(), "*", f"{sid}.jsonl"))
    return hits[0] if hits else None


def read_rows(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def role_of(agent_type):
    name = (agent_type or "?").split(":")[-1]
    return name[5:] if name.startswith("bmad-") else name


def model_of(model):
    return re.sub(r"^claude-", "", model or "?")


class Transcript:
    """One transcript file: tokens, tools, child calls, texts, time."""

    def __init__(self, path):
        self.rows = read_rows(path)
        self.tokens = collections.defaultdict(lambda: dict.fromkeys(ZERO, 0))
        self.tools = collections.Counter()
        self.calls = {}               # tool_use id → input (Agent only)
        self.tool_ids = set()
        self.texts = []
        self.reports = []             # SubagentHandback messages
        seen_msg, seen_tool = set(), set()
        stamps = [r.get("timestamp") for r in self.rows if r.get("timestamp")]
        self.started, self.ended = (min(stamps), max(stamps)) if stamps else (None, None)
        replies, headed, handbacks = [], [], []
        for r in self.rows:
            msg = r.get("message") if isinstance(r.get("message"), dict) else None
            if not msg or r.get("type") != "assistant":
                continue
            if r.get("timestamp"):
                replies.append(r["timestamp"])
            mid = msg.get("id")
            if mid and mid not in seen_msg and msg.get("usage"):
                seen_msg.add(mid)
                acc = self.tokens[model_of(msg.get("model"))]
                for src, dst in TOKEN_KEYS:
                    acc[dst] += msg["usage"].get(src) or 0
            acc = self.tokens[model_of(msg.get("model"))]
            for c in msg.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text":
                    acc["out_est"] += round(len(c.get("text") or "") / CHARS_PER_TOKEN)
                elif c.get("type") == "tool_use":
                    acc["out_est"] += round(len(json.dumps(c.get("input"), ensure_ascii=False)) / CHARS_PER_TOKEN)
                    if c.get("name") == "SubagentHandback":
                        self.reports.append((c.get("input") or {}).get("message") or "")
                        handbacks.append(r.get("timestamp"))
                if c.get("type") == "tool_use" and c.get("id") not in seen_tool:
                    seen_tool.add(c.get("id"))
                    self.tool_ids.add(c.get("id"))
                    self.tools[c.get("name") or "?"] += 1
                    if c.get("name") in ("Agent", "Task"):
                        self.calls[c.get("id")] = c.get("input") or {}
                elif c.get("type") == "text" and c.get("text"):
                    self.texts.append(c["text"])
                    if REPORT_RE.search(c["text"]):
                        headed.append(r.get("timestamp"))
        # The time of the report: the last handback, else the last text with a report header.
        self.reported = (max(filter(None, handbacks), default=None) or max(filter(None, headed), default=None)
                         or max(replies, default=None) or self.ended)

    def report(self):
        """Texts to read the report from: the handbacks, else everything the agent wrote."""
        return self.reports or self.texts


def add_tokens(dst, src):
    for model, acc in src.items():
        d = dst.setdefault(model, dict.fromkeys(ZERO, 0))
        for k, v in acc.items():
            d[k] = d.get(k, 0) + v


def total(tokens_by_model):
    t = dict.fromkeys(ZERO, 0)
    for acc in tokens_by_model.values():
        for k, v in acc.items():
            t[k] = t.get(k, 0) + v
    return t


def minutes(a, b):
    try:
        da = datetime.datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = datetime.datetime.fromisoformat(b.replace("Z", "+00:00"))
        return round((db - da).total_seconds() / 60, 1)
    except (AttributeError, ValueError):
        return None


def stamp(value):
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def busy_minutes(spans):
    """Minutes covered by the (start, end) spans: overlaps count once, gaps not at all.
    None when no span has both ends."""
    parsed = sorted((a, b) for a, b in ((stamp(a), stamp(b)) for a, b in spans) if a and b and b >= a)
    if not parsed:
        return None
    seconds, last = 0.0, None
    for a, b in parsed:
        if last and a < last:
            a = last
        if not last or b > last:
            seconds += (b - a).total_seconds()
            last = b
    return round(seconds / 60, 1)


def header(texts):
    """The story-runner machine header: the last text with STATUS:."""
    for text in reversed(texts):
        if HEAD_RE["STATUS"].search(text):
            return {k.lower(): (m.group(1) if (m := rx.search(text)) else None) for k, rx in HEAD_RE.items()}
    return {}


def review(spec_path, repo=None):
    """Passes and findings from the spec's "## Review Triage Log" — counters only.
    A spec from a removed worktree is read from the repository's artifacts by its file name."""
    paths = [spec_path]
    if spec_path and repo:
        paths = [os.path.join(repo, spec_path),               # a relative path is from the repo
                 os.path.join(repo, ARTIFACTS, os.path.basename(spec_path))]
    text = None
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            break
        except (OSError, TypeError):
            continue
    if text is None:
        return None
    i = text.find("## Review Triage Log")
    if i < 0:
        return None
    log = text[i:]
    j = log.find("\n## ", 5)
    log = log[:j] if j > 0 else log
    by_verdict, by_action, by_layer = collections.Counter(), collections.Counter(), collections.Counter()
    passes = findings = 0
    for m in VERDICTS_RE.finditer(log):
        passes += 1
        findings += int(m.group(1))
        for v, n in VERDICT_ITEM.findall(m.group(2)):
            by_verdict[v.lower()] += int(n)
    for _, _, bracketed, plain, layer in FINDING_RE.findall(log):
        action = bracketed or plain
        if action:
            by_action[action.lower()] += 1
        if layer:
            by_layer[layer.lower()] += 1
    return {"passes": passes, "findings": findings, "by_verdict": dict(by_verdict),
            "by_action": dict(by_action), "by_layer": dict(by_layer)}


def task_id(prompt):
    """Task mode story id: the spec slug, then the task ref, then a check prompt's `Story: <slug>`."""
    m = SLUG_RE.search(prompt)
    if m:
        return m.group(1)
    m = TASK_RE.search(prompt)
    if m:
        ref = re.sub(r"[^\w.-]+", "", m.group(1)).strip("-.")
        if ref:
            return f"task-{ref}"
    m = STORY_SLUG_RE.search(prompt)
    return m.group(1) if m else None


def commit_of(value):
    value = (value or "").strip().strip("`")
    return None if not value or value.lower() in NO else value[:12]


def as_int(value):
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


def collect(session_path, repo=None):
    """→ [records] for a session: the orchestrator + one record per story."""
    sid = os.path.basename(session_path)[:-6]
    main = Transcript(session_path)
    sub_dir = os.path.join(os.path.dirname(session_path), sid, "subagents")
    agents = {}
    for meta_path in glob.glob(os.path.join(sub_dir, "*.meta.json")):
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            continue
        aid = os.path.basename(meta_path)[:-len(".meta.json")]
        agents[aid] = {"meta": meta, "t": Transcript(meta_path[:-len(".meta.json")] + ".jsonl")}
    owner = {tid: None for tid in main.tool_ids}          # tool_use id → the agent that made it
    for aid, a in agents.items():
        for tid in a["t"].tool_ids:
            owner[tid] = aid

    ROOTS = ("story-runner", "verifier")

    def root(aid):
        """The story's top agent (story-runner or verifier) this agent worked under."""
        seen = set()
        while aid and aid not in seen:
            seen.add(aid)
            if role_of(agents[aid]["meta"].get("agentType")) in ROOTS:
                return aid
            aid = owner.get(agents[aid]["meta"].get("toolUseId"))
        return None

    def prompt_of(a):
        tid = a["meta"].get("toolUseId")
        prompt = (main.calls.get(tid) or {}).get("prompt", "")
        for other in agents.values():          # called by someone other than this orchestrator
            prompt = prompt or (other["t"].calls.get(tid) or {}).get("prompt", "")
        return prompt

    # All runs of one story — first run, fix runs and checks — make one record.
    groups = collections.OrderedDict()
    for aid, a in sorted(agents.items(), key=lambda kv: kv[1]["t"].started or ""):
        role = role_of(a["meta"].get("agentType"))
        if role not in ROOTS:
            continue
        prompt = prompt_of(a)
        sm, tm = STORY_RE.search(prompt), task_id(prompt)
        story = f"{int(sm.group(1))}-{norm_num(sm.group(2))}" if sm else (tm or f"?-{aid}")
        g = groups.setdefault(story, {"sm": sm, "tm": tm, "level": None, "runners": [], "verifiers": []})
        lm = LEVEL_RE.search(prompt)
        g["level"] = g["level"] or (lm.group(1) if lm else None)
        g["runners" if role == "story-runner" else "verifiers"].append(aid)

    records = []
    for story, g in groups.items():
        roots = set(g["runners"] + g["verifiers"])
        # A fix run is a story-runner started after the story's first check; a rerun before it is not.
        checked = min((agents[a]["t"].started for a in g["verifiers"] if agents[a]["t"].started), default=None)
        fixes = [a for a in g["runners"] if checked and (agents[a]["t"].started or "") > checked]
        heads = [header(agents[aid]["t"].report()) for aid in g["runners"]]
        head = next((h for h in reversed(heads) if h), {})
        main_run = next((h for a, h in zip(reversed(g["runners"]), reversed(heads)) if a not in fixes and h), {})
        verdicts = []
        for aid in g["verifiers"]:
            m = re.search(r"^VERDICT:\s*(\w+)", "\n".join(agents[aid]["t"].report()), re.M)
            verdicts.append(m.group(1) if m else "?")
        by_role, by_model, by_role_model = {}, {}, {}
        roles, tools = collections.Counter(), collections.Counter()
        started = min((agents[a]["t"].started for a in roots if agents[a]["t"].started), default=None)
        # The story ends with the last report of its runs and checks: an agent that wakes up
        # after the report (a background command finished) does not stretch it.
        ended = max((agents[a]["t"].reported for a in roots if agents[a]["t"].reported), default=None)
        for kid, k in agents.items():
            if root(kid) not in roots:
                continue
            role = role_of(k["meta"].get("agentType"))
            roles[role] += 1
            tools.update(k["t"].tools)
            add_tokens(by_model, k["t"].tokens)
            add_tokens(by_role_model.setdefault(role, {}), k["t"].tokens)
            acc = by_role.setdefault(role, dict.fromkeys(ZERO, 0))
            for key, value in total(k["t"].tokens).items():
                acc[key] += value
        sm, tm = g["sm"], g["tm"]
        rec = {"id": f"{sid}:{story}", "session": sid, "kind": "story" if sm else ("task" if tm else "?"),
               "story": story, "epic": int(sm.group(1)) if sm else None, "level": g["level"],
               "started": started, "ended": ended,
               # Time the runs and checks worked: a pause between a blocked run and its rerun is not counted.
               "minutes": busy_minutes((agents[a]["t"].started, agents[a]["t"].reported) for a in roots),
               "status": head.get("status"), "commit": commit_of(head.get("commit")),
               "files": as_int(main_run.get("files")), "review_passes_used": as_int(main_run.get("passes")),
               "followup_open": bool(head.get("followup_open")
                                     and head["followup_open"].split()[0].strip("—,.;:").lower() not in NO),
               "deferred": as_int(head.get("deferred")),
               "fix_runs": len(fixes), "verify": verdicts,
               "agents": dict(roles), "tools": dict(tools),
               "tokens": {"total": total(by_model), "by_model": by_model, "by_role": by_role,
                          "by_role_model": by_role_model},
               "review": review(head.get("spec"), repo)}
        records.append(rec)
    if records:
        orch = {"id": f"{sid}:orchestrator", "session": sid, "kind": "orchestrator",
                "started": main.started, "ended": main.ended, "minutes": minutes(main.started, main.ended),
                "stories": [r["story"] for r in records], "tools": dict(main.tools),
                "tokens": {"total": total(main.tokens), "by_model": dict(main.tokens)}}
        records.insert(0, orch)
    return records


def load(repo):
    path = stats_path(repo)
    return [r for r in read_rows(path) if isinstance(r, dict) and r.get("id")]


def stats_path(repo):
    root = Path(main_tree(repo)).resolve()
    path = root / STATS
    if not path.resolve().is_relative_to(root):
        raise ValueError("statistics path escapes the project")
    return str(path)


def save(repo, records):
    """Replace the lines of the same sessions with new ones, keep the rest.

    The SessionEnd hook records in the background, so two writers can meet: a lock
    covers read-and-write, and the file is replaced atomically.
    """
    repo = main_tree(repo)
    ensure_excluded(repo, ".auto-bmad/")
    path = stats_path(repo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock_fd = os.open(path + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sessions = {r["session"] for r in records}
        previous = load(repo)
        snapshots = {r["id"]: r for r in previous}
        records = [{**r, "review": snapshots.get(r["id"], {}).get("review")}
                   if r.get("source") == "cli" and r.get("review") is None else r for r in records]
        incoming = {r["session"]: r for r in records if r.get("source") == "cli"}
        stale = {r["session"] for r in previous if r["session"] in incoming and
                 r.get("revision", 0) > incoming[r["session"]].get("revision", 0)}
        kept = [r for r in previous if r.get("session") not in sessions or r.get("session") in stale]
        records = [r for r in records if r["session"] not in stale]
        rows = sorted(kept + records, key=lambda r: (r.get("started") or "", r["id"]))
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".runs-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    return path


ROUTES = ("patch", "defer", "reject", "intent_gap", "bad_spec")
VERDICTS = ("high", "medium", "low", "maybe-false", "false")


def pct(n, total):
    """A share in whole percent, half rounded up (round() would round 12.5 to 12)."""
    return int(100 * n / total + 0.5) if total else None


def triage(stories):
    """How the session routed the findings: shares of patch / defer / reject and of the spec
    routes (intent_gap, bad_spec), and the shares of the low and false verdicts. Labels the
    engine does not define are left out. A worse triage shows as more reject and fewer patch;
    `low` mostly comes from the screening rule (fact B), `false` from reading the code."""
    routes, verdicts = collections.Counter(), collections.Counter()
    for r in stories:
        rv = r.get("review") or {}
        routes.update({k: v for k, v in (rv.get("by_action") or {}).items() if k in ROUTES})
        verdicts.update({k: v for k, v in (rv.get("by_verdict") or {}).items() if k in VERDICTS})
    routed, graded = sum(routes.values()), sum(verdicts.values())
    return {"routed": routed, "routes": dict(routes),
            "patch_pct": pct(routes["patch"], routed), "defer_pct": pct(routes["defer"], routed),
            "reject_pct": pct(routes["reject"], routed),
            "spec_pct": pct(routes["intent_gap"] + routes["bad_spec"], routed),
            "graded": graded, "low_pct": pct(verdicts["low"], graded),
            "false_pct": pct(verdicts["false"], graded)}


def summarize(rows):
    stories = [r for r in rows if r.get("kind") in ("story", "task")]
    orch = [r for r in rows if r.get("kind") == "orchestrator"]

    def avg(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 1) if values else None

    out = {"stories": len(stories),
           "done": sum(1 for r in stories if r.get("status") == "done"),
           "blocked": sum(1 for r in stories if r.get("status") == "blocked"),
           "minutes_total": round(sum(r.get("minutes") or 0 for r in stories), 1),
           "minutes_avg": avg([r.get("minutes") for r in stories]),
           "tokens_out_avg": avg([output(r["tokens"]["total"]) for r in stories]),
           "tokens_new_in_avg": avg([r["tokens"]["total"]["in"] + r["tokens"]["total"]["cache_write"] for r in stories]),
           "tokens_cache_read_avg": avg([r["tokens"]["total"]["cache_read"] for r in stories]),
           "review_passes_avg": avg([(r.get("review") or {}).get("passes") for r in stories]),
           "findings_avg": avg([(r.get("review") or {}).get("findings") for r in stories]),
           "agents_avg": avg([sum((r.get("agents") or {}).values()) for r in stories]),
           "orchestrator_out_est": sum(r["tokens"]["total"]["out_est"] for r in orch)}
    out["triage"] = triage(stories)
    out["by_status"] = dict(collections.Counter(r.get("status") or "?" for r in stories))
    by_level = collections.defaultdict(list)
    for r in stories:
        by_level[r.get("level") or "?"].append(r)
    out["by_level"] = {lvl: {"stories": len(rs), "minutes_avg": avg([r.get("minutes") for r in rs]),
                             "tokens_out_avg": avg([output(r["tokens"]["total"]) for r in rs]),
                             "findings_avg": avg([(r.get("review") or {}).get("findings") for r in rs]),
                             "triage": triage(rs)}
                       for lvl, rs in sorted(by_level.items())}
    roles = collections.defaultdict(lambda: dict.fromkeys(ZERO, 0))
    for r in stories:
        for role, acc in (r["tokens"].get("by_role") or {}).items():
            for k, v in acc.items():
                roles[role][k] = roles[role].get(k, 0) + v
    out["by_role"] = dict(roles)
    # Which models each role ran on, by output; records written before by_role_model have none.
    role_models = collections.defaultdict(collections.Counter)
    for r in stories:
        for role, models in (r["tokens"].get("by_role_model") or {}).items():
            for model, acc in models.items():
                role_models[role][model] += output(acc)
    out["role_models"] = {role: [m for m, _ in c.most_common()] for role, c in role_models.items()}
    tools = collections.Counter()
    for r in rows:
        tools.update(r.get("tools") or {})
    out["tools_top"] = dict(tools.most_common(10))
    models, epics = {}, {}
    for row in stories:
        add_tokens(models, row["tokens"].get("by_model", {}))
        epic = row.get("epic")
        if epic is not None:
            group = epics.setdefault(str(epic), {"stories": 0, "by_model": {}, "by_role": {}})
            group["stories"] += 1
            add_tokens(group["by_model"], row["tokens"].get("by_model", {}))
            add_tokens(group["by_role"], row["tokens"].get("by_role", {}))
    for group in epics.values():
        group["tokens"] = total(group["by_model"])
    out.update(by_model=models, by_epic=epics, tokens=total(models))
    return out


def output(tokens):
    return tokens.get("out_est", 0) + tokens.get("out_exact", 0)


def kfmt(n):
    if n is None:
        return "—"
    return f"{n / 1e6:.1f}M" if n >= 1e6 else (f"{n / 1e3:.0f}k" if n >= 1e3 else str(int(n)))


def table(rows, summary, calls=False):
    stories = [r for r in rows if r.get("kind") in ("story", "task")]
    cli = any(r.get("source") == "cli" for r in rows)
    label = "out*" if cli else "out≈"
    lines = [f"{'story':<10} {'level':<7} {'status':<8} {'min':>5} {label:>7} {'in':>7} {'cache':>7} "
             f"{'agents':>7} {'passes':>8} {'findings':>8}"]
    for r in stories:
        t, rv = r["tokens"]["total"], r.get("review") or {}
        lines.append(f"{(r.get('story') or '?'):<10} {(r.get('level') or '?'):<7} {(r.get('status') or '?'):<8} "
                     f"{(r.get('minutes') or 0):>5.0f} {kfmt(output(t)):>7} {kfmt(t['in'] + t['cache_write']):>7} "
                     f"{kfmt(t['cache_read']):>7} {sum((r.get('agents') or {}).values()):>7} "
                     f"{rv.get('passes', '—'):>8} {rv.get('findings', '—'):>8}")
    s = summary
    lines += ["",
              f"Stories: {s['stories']} (done {s['done']}, blocked {s['blocked']}) · time {s['minutes_total']:.0f} min, "
              f"{s['minutes_avg']} min per story on average",
              f"Tokens per story on average: output {kfmt(s['tokens_out_avg'])}, new input {kfmt(s['tokens_new_in_avg'])}, "
              f"cache read {kfmt(s['tokens_cache_read_avg'])} · orchestrator, total output: {kfmt(s['orchestrator_out_est'])}",
              f"Review: {s['review_passes_avg']} passes on average, {s['findings_avg']} findings, "
              f"{s['agents_avg']} subagents per story"]
    t = s.get("triage") or {}
    if t.get("routed"):
        lines.append(f"Triage of {t['routed']} findings: patch {t['patch_pct']}%, defer {t['defer_pct']}%, "
                     f"reject {t['reject_pct']}%, to the spec {t['spec_pct']}%"
                     + (f" · verdicts of {t['graded']}: low {t['low_pct']}%, false {t['false_pct']}%"
                        if t.get("graded") else ""))
    if s["by_role"]:
        models = s.get("role_models") or {}
        lines.append("Output by role: " + ", ".join(
            f"{k} {kfmt(output(v))}" + (f" ({', '.join(models[k])})" if models.get(k) else "")
            for k, v in sorted(s["by_role"].items(), key=lambda kv: -output(kv[1]))))
    if s["tools_top"]:
        lines.append("Tools: " + ", ".join(f"{k} {v}" for k, v in s["tools_top"].items()))
    if cli:
        t = s["tokens"]
        lines.append("Output by configured model: " + ", ".join(f"{m} {kfmt(output(v))}" for m, v in sorted(s["by_model"].items())))
        lines.append(f"CLI usage: complete {t.get('usage_complete', 0)}, partial {t.get('usage_partial', 0)}, "
                     f"unavailable {t.get('usage_unavailable', 0)} calls. Counts are reported subtotals; unknown is not zero.")
        lines.append("Codex input includes cached input: new input = input - cached. Output is reported, cache write is unavailable; "
                     "model labels are requested IDs, not independently observed models. Legacy output remains estimated. Prices are not counted.")
    else:
        lines.append("in — input + cache write, cache — cache read: exact, from the transcript. out≈ — an estimate from "
                     "reply text and tool calls, without the model's reasoning. Prices are not counted.")
    if calls:
        lines.append("\nCLI calls (reported token subtotals):")
        for row in stories:
            for call in row.get("calls", []):
                u = call["usage"]
                def exact(value):
                    return "—" if value is None else str(value)
                lines.append(f"{row.get('story', '?')} {call['id']} {call['role']} {call['model_requested']} "
                             f"{call['execution_status']} input={exact(u['input_tokens'])} "
                             f"cached={exact(u['cached_input_tokens'])} output={exact(u['output_tokens'])} {call['usage_status']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--session", required=True)
    r.add_argument("--repo", default=".")
    b = sub.add_parser("backfill")
    b.add_argument("--repo", default=".")
    s = sub.add_parser("show")
    s.add_argument("--epic", type=int)
    s.add_argument("--last", type=int)
    s.add_argument("--json", action="store_true")
    s.add_argument("--calls", action="store_true", help="show each CLI role invocation, including unknown usage")
    s.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    if not os.path.isdir(repo):
        print(json.dumps({"error": f"no such directory {repo}"}, ensure_ascii=False))
        return 1

    if a.cmd in ("record", "backfill"):
        import cli_stats
        cli = cli_stats.publish(repo, a.session if a.cmd == "record" else None)
        if a.cmd == "record" and cli.get("recorded"):
            print(json.dumps(cli, ensure_ascii=False))
            return 0
        paths = [find_session(repo, a.session)] if a.cmd == "record" else sorted(session_files(repo).values())
        paths = [p for p in paths if p]
        if a.cmd == "backfill":
            # Sessions already recorded keep their rows: a rerun of the parser must not
            # rewrite good history with what the current version can read of old transcripts.
            known = {r.get("session") for r in load(repo)}
            paths = [p for p in paths if os.path.splitext(os.path.basename(p))[0] not in known]
        records = [rec for p in paths for rec in collect(p, repo)]
        if not records and cli.get("recorded"):
            print(json.dumps(cli, ensure_ascii=False))
            return 0
        if not records:
            print(json.dumps(cli if cli.get("error") else {"recorded": 0, "note": "no story-runner runs in the sessions"}, ensure_ascii=False))
            return 1 if cli.get("error") else 2
        path = save(repo, records)
        print(json.dumps({"recorded": sum(1 for x in records if x["kind"] != "orchestrator") + cli.get("recorded", 0),
                          "sessions": len({x["session"] for x in records}), "file": path}, ensure_ascii=False))
        if cli.get("error"):
            print("CLI statistics refresh failed: " + cli["error"], file=sys.stderr)
            return 1
        return 0

    import cli_stats
    refreshed = cli_stats.publish(repo, None)
    try:
        rows = load(repo)
    except (OSError, ValueError) as e:
        rows = []
        refreshed["error"] = str(e)
    if a.epic is not None:
        keep = {r["session"] for r in rows if r.get("epic") == a.epic}
        rows = [r for r in rows if r.get("epic") == a.epic or (r.get("kind") == "orchestrator" and r["session"] in keep)]
    if a.last:
        def run_id(r):
            return "cli-queue:" + r["queue_id"] if r.get("queue_id") else r["session"]
        sessions = sorted({run_id(r): r.get("started") or "" for r in rows}.items(), key=lambda kv: kv[1])
        keep = {sid for sid, _ in sessions[-a.last:]}
        rows = [r for r in rows if run_id(r) in keep]
    if not [r for r in rows if r.get("kind") != "orchestrator"]:
        if refreshed.get("error"):
            print(json.dumps({"stories": 0, "error": refreshed["error"], "refresh": refreshed}, ensure_ascii=False))
            return 1
        print(json.dumps({"stories": 0, "note": "no statistics: auto-bmad stats backfill"}, ensure_ascii=False))
        return 2
    summary = summarize(rows)
    if a.json:
        print(json.dumps({"summary": summary, "rows": rows, "refresh": refreshed}, ensure_ascii=False, indent=2))
    else:
        print(table(rows, summary, calls=a.calls))
        if refreshed.get("error"):
            print("Statistics refresh failed: " + refreshed["error"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
