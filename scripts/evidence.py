#!/usr/bin/env python3
"""Code excerpts for a list of review findings, in one call.

Triage in step-04 must name the code it read before it rejects a finding or grades it
`false` or `low`. One `grep` or `git diff` per finding means dozens of calls per story,
and every call re-reads the whole session context. This script answers all findings of
a pass at once.

The input is a JSON file (written with the Write tool, no heredoc):

    {
      "base": "<baseline_revision>",
      "findings": [
        {"id": "1", "file": "src/a.py", "lines": "40-52"},
        {"id": "2", "file": "src/b.py", "lines": "12", "diff": true},
        {"id": "3", "file": "src/c.py", "grep": "parse_date\\\\(", "grep_in": "."}
      ]
    }

Per finding: `file` (relative to the repo), `lines` ("12", "40-52", "12,40-52", a number or a
list of them), `grep` (a regular expression, `git grep -E`), `grep_in` (where to grep: a
path, "." — the whole repository; the finding's file by default), `diff` (true — the hunks of
`git diff <base> -- <file>` that touch the lines, all of them without `lines`). At least one
of `lines`, `grep` and `diff` is needed.

Usage:
    evidence.py --input <file.json> [--base <rev>] [--context 3] [--repo .]

JSON on stdout: `findings` — per finding `id`, `file`, and what was asked: `code` (the lines
with their numbers, plus `--context` lines around), `diff`, `grep` (`hits` as path:line: text,
`count`), `error` for a part that failed (no such file, a bad pattern). The excerpts are cut
at 120 lines, the grep hits at 20.
Exit 0 — answered (a finding's own error does not count), 1 — call error (no input, broken JSON).
"""

import argparse
import json
import os
import re
import subprocess
import sys

from gitexclude import ensure_excluded

MAX_LINES = 120
MAX_HITS = 20
REV = re.compile(r"^[\w./~^@{}-]+$")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def parse_lines(value):
    """"12", "40-52" (or an en / em dash), "12,40-52", 12 or a list of them → [(from, to)]; bad — ValueError."""
    if value is None or value == "":
        return []
    parts = value if isinstance(value, list) else [value]
    out = []
    for part in parts:
        for piece in str(part).split(","):
            m = re.fullmatch(r"\s*L?(\d+)\s*(?:[-–—:]\s*L?(\d+)\s*)?", piece)
            if not m:
                raise ValueError(f"cannot parse lines {value!r}")
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            out.append((min(a, b), max(a, b)))
    return out


def merge(ranges, context, last):
    """Ranges widened by context, clipped to the file, overlapping ones joined."""
    out = []
    for a, b in sorted((max(1, a - context), min(last, b + context)) for a, b in ranges):
        if a > b:
            continue
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def cut(lines):
    if len(lines) <= MAX_LINES:
        return "\n".join(lines)
    return "\n".join(lines[:MAX_LINES] + [f"…(cut: {len(lines) - MAX_LINES} more lines)"])


def inside(repo, path):
    """The file's absolute path when it lies inside the repo, else None."""
    full = os.path.realpath(os.path.join(repo, path))
    root = os.path.realpath(repo)
    return full if full == root or full.startswith(root + os.sep) else None


def code_of(full, ranges, context):
    with open(full, encoding="utf-8", errors="replace") as fh:
        text = fh.read().split("\n")
    if text and text[-1] == "":
        text.pop()
    blocks = merge(ranges, context, len(text))
    if not blocks:
        return f"(the file has {len(text)} lines)"
    lines = []
    for i, (a, b) in enumerate(blocks):
        if i:
            lines.append("…")
        lines += [f"{n}: {text[n - 1]}" for n in range(a, b + 1)]
    return cut(lines)


def diff_of(repo, base, path, ranges, context):
    proc = git(repo, "diff", base, "--", path)
    if proc.returncode:
        return None, (proc.stderr.strip() or "git diff failed")[:300]
    if not proc.stdout.strip():
        tracked = git(repo, "ls-files", "--error-unmatch", "--", path).returncode == 0
        return ("(no changes since the base)" if tracked else
                "(not tracked: a new file, its code is the change)"), None
    window = [(a - context, b + context) for a, b in ranges]
    out, header, new, gap = [], None, 0, False
    for line in proc.stdout.split("\n"):
        m = HUNK.match(line)
        if m:
            header, new, gap = line, int(m.group(1)), False
            continue
        if header is None or not line or line[0] not in " +-":
            continue
        # A removed line sits at the new-side position of the next kept line.
        if not window or any(a <= new <= b for a, b in window):
            if header:
                out.append(header)
                header = ""
            elif gap:
                out.append("…")
            gap = False
            out.append(line)
        elif header == "":
            gap = True
        if line[0] != "-":
            new += 1
    if not out:
        return "(the diff of this file does not touch these lines)", None
    return cut(out), None


def grep_of(repo, pattern, where):
    proc = git(repo, "grep", "-n", "-I", "-E", "--untracked", "-e", pattern, "--", where)
    if proc.returncode not in (0, 1):
        return {"pattern": pattern, "in": where, "error": (proc.stderr.strip() or "git grep failed")[:300]}
    hits = [h for h in proc.stdout.split("\n") if h]
    out = {"pattern": pattern, "in": where, "count": len(hits), "hits": hits[:MAX_HITS]}
    if len(hits) > MAX_HITS:
        out["hits"].append(f"…(cut: {len(hits) - MAX_HITS} more)")
    return out


def answer(repo, finding, base, context):
    if not isinstance(finding, dict):
        return {"error": "a finding must be a JSON object"}
    path = str(finding.get("file") or "").strip()
    out = {"id": finding.get("id"), "file": path or None}
    errors = []
    try:
        ranges = parse_lines(finding.get("lines"))
    except ValueError as e:
        ranges = []
        errors.append(str(e))
    pattern, want_diff = finding.get("grep"), finding.get("diff") is True
    if not (ranges or pattern or want_diff):
        out["error"] = "; ".join(errors) or "give lines, grep or diff"
        return out
    full = inside(repo, path) if path else None
    if path and not full:
        errors.append(f"{path} is outside the repository")
    if (ranges or want_diff) and not path:
        errors.append("lines and diff need a file")
    if ranges and full:
        if os.path.isfile(full):
            out["lines"] = finding.get("lines")
            out["code"] = code_of(full, ranges, context)
        else:
            errors.append(f"no such file {path}")
    if want_diff and full:
        rev = str(finding.get("base") or base or "")
        if not REV.match(rev) or rev.startswith("-"):
            errors.append("diff needs a base revision (`base` in the input or --base)")
        else:
            out["diff"], err = diff_of(repo, rev, path, ranges, context)
            if err:
                errors.append(err)
    if pattern:
        where = str(finding.get("grep_in") or path or ".")
        if not inside(repo, where):
            errors.append(f"{where} is outside the repository")
        else:
            out["grep"] = grep_of(repo, str(pattern), where)
    if errors:
        out["error"] = "; ".join(errors)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--input", required=True, help="JSON file with the findings")
    ap.add_argument("--base", help="base revision for `diff`, when the input has no `base`")
    ap.add_argument("--context", type=int, default=3, help="lines around each range (default 3)")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    # The input lives under .auto-bmad/: unignored, it would leave the engine's tree dirty,
    # even when the input turns out to be broken.
    if os.path.isdir(repo):
        ensure_excluded(repo, ".auto-bmad/")
    try:
        if not os.path.isdir(repo):
            raise ValueError(f"no such directory {repo}")
        with open(a.input, encoding="utf-8") as fh:
            data = json.load(fh)
        findings = data.get("findings") if isinstance(data, dict) else data
        if not isinstance(findings, list):
            raise ValueError("the input needs a `findings` list")
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    base = (data.get("base") if isinstance(data, dict) else None) or a.base
    out = [answer(repo, f, base, max(0, a.context)) for f in findings]
    print(json.dumps({"count": len(out), "findings": out, "error": None}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
