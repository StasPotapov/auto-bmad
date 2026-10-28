#!/usr/bin/env python3
"""Syncs sprint-status.yaml after finished stories.

Moves stories to done, lifts the parent epic (backlog → in-progress, all stories
done → done) and updates last_updated in the same format as the nearby generated.
The edit is line by line, so the file's comments, order and formatting stay: project
headers differ (fields active in some, commented out in others).

Usage:
    sync_sprint.py --story 1-3 [--story 1-5] [--status done] [--repo .] [--dry-run]

Prints JSON: what changed. Exit 0 — written, 1 — error, 2 — nothing to change.
"""

import argparse
import json
import os
import re
import sys

from datetime import datetime

from common import SPRINT_REL, key_story, parse_story

ENTRY = re.compile(r"^(\s+)([^\s#][^:]*):(\s*)(.*)$")
# Date formats of generated / last_updated: (pattern, strftime format).
STAMP_FORMATS = [
    (r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}$", "%m-%d-%Y %H:%M"),
    (r"^\d{2}-\d{2}-\d{4}$", "%m-%d-%Y"),
    (r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}Z$", "%Y-%m-%dT%H:%M:%SZ"),
    (r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$", "%Y-%m-%d %H:%M:%S"),
    (r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$", "%Y-%m-%d %H:%M"),
    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
]


def parse_stamp(value):
    """A generated / last_updated value → an aware datetime; not a known date — None.

    A date without a zone is local time; an ISO date with an offset keeps it.
    """
    bare = (value or "").split("#", 1)[0].strip().strip("'\"")
    stamp = None
    try:
        stamp = datetime.fromisoformat(bare)
    except ValueError:
        for pattern, fmt in STAMP_FORMATS:
            if re.match(pattern, bare):
                try:
                    stamp = datetime.strptime(bare, fmt)
                except ValueError:
                    return None
                break
    if stamp is None:
        return None
    return stamp if stamp.tzinfo else stamp.astimezone()


def stamp_like(sample):
    """The date in the sample's format. An unknown format — None, the field is left alone."""
    now = datetime.now()
    sample = (sample or "").strip()
    quote = sample[0] if sample[:1] in ("'", '"') else ""
    bare = sample.strip("'\"")
    for pattern, fmt in STAMP_FORMATS:
        if re.match(pattern, bare):
            if "T" in bare and "T" not in fmt:
                fmt = fmt.replace(" ", "T")
            return f"{quote}{now.strftime(fmt)}{quote}"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", action="append", required=True,
                    help="story id (repeatable): 1-3")
    ap.add_argument("--status", default="done")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = os.path.join(args.repo, SPRINT_REL)
    if not os.path.exists(path):
        message = f"not found: {path}"
        print(message, file=sys.stderr)
        print(json.dumps({"error": message, "path": os.path.abspath(path)},
                         ensure_ascii=False))
        return 1

    wanted = set()
    for raw in args.story:
        parsed = parse_story(raw)
        if not parsed:
            message = f"cannot parse the story id: {raw!r}"
            print(message, file=sys.stderr)
            print(json.dumps({"error": message}, ensure_ascii=False))
            return 1
        wanted.add(parsed)
    epics = {e for e, _ in wanted}

    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    changed, generated_sample, in_status = [], None, False
    found = set()
    story_state = {}       # epic -> story statuses after the edit
    epic_lines = {}        # epic -> index of the epic-N line

    for i, line in enumerate(lines):
        if not line.startswith((" ", "\t")) and ":" in line:
            head, _, value = line.partition(":")
            head = head.strip()
            in_status = head == "development_status"
            if head == "generated":
                generated_sample = value.strip()
            continue
        if not in_status:
            continue
        m = ENTRY.match(line)
        if not m:
            continue
        indent, key, gap, value = m.groups()
        value = value.split("#", 1)[0].strip()

        if key.startswith("epic-") and key.split("-")[1].isdigit() and "-" not in key[5:]:
            epic_lines[int(key.split("-")[1])] = i
            continue
        ks = key_story(key)
        if not ks or key.endswith("-retrospective"):
            continue
        epic, num, _ = ks
        found.add((epic, num))
        new_value = args.status if (epic, num) in wanted else value
        if (epic, num) in wanted and value != args.status:
            lines[i] = f"{indent}{key}:{gap}{args.status}"
            changed.append({"key": key, "from": value, "to": args.status})
        story_state.setdefault(epic, []).append(new_value)

    epic_changes = []
    for epic in sorted(epics):
        idx = epic_lines.get(epic)
        if idx is None:
            continue
        m = ENTRY.match(lines[idx])
        indent, key, gap, value = m.groups()
        value = value.split("#", 1)[0].strip()
        states = story_state.get(epic, [])
        target = "done" if states and all(s == "done" for s in states) else "in-progress"
        if target == "in-progress" and value not in ("backlog", "done"):
            continue
        if value != target:
            lines[idx] = f"{indent}{key}:{gap}{target}"
            epic_changes.append({"key": key, "from": value, "to": target})

    stamp = None
    if changed or epic_changes:
        for i, line in enumerate(lines):
            if not line.startswith("last_updated:"):
                continue
            value = line.partition(":")[2]
            had_comment = "#" in value
            own = value.split("#", 1)[0].strip()
            # The sample is last_updated itself: generated may use another format.
            stamp = stamp_like(own) or stamp_like(generated_sample)
            if stamp:
                # A trailing comment described the previous edit: replace it; never add one.
                tail = ""
                if had_comment:
                    moved = ", ".join(c["key"] for c in changed) or "epic statuses"
                    tail = f"  # auto-bmad: {moved} → {args.status}"
                lines[i] = f"last_updated: {stamp}{tail}"
            break

    missing = sorted(f"{e}-{n}" for e, n in wanted - found)
    result = {
        "path": os.path.abspath(path),
        "stories_changed": changed,
        "epics_changed": epic_changes,
        "last_updated": stamp,
        "dry_run": args.dry_run,
        "note": None if changed else "no story changed its status (already set?)",
    }
    if not (changed or epic_changes):
        result["error"] = ("nothing to change: the stories already have this status or are not in the file"
                           + (f" (not found: {', '.join(missing)})" if missing else ""))
        print(result["error"], file=sys.stderr)
    if missing:
        result["not_found"] = missing

    if not args.dry_run and (changed or epic_changes):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (changed or epic_changes) else 2


if __name__ == "__main__":
    sys.exit(main())
