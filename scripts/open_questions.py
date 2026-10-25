#!/usr/bin/env python3
"""Keeps the single open questions file of an epic.

At the end of every story the skill sends its "Needs attention" items here, and the
epic's file epic-<N>-open-questions.md
collects them in one place, with a link to the spec and the commit.

The script owns the file, not the model: a story section is framed by a pair of anchors
`<!-- story:5-3 -->` … `<!-- /story:5-3 -->` and replaced whole by them. A rerun of a
story updates only its section; everything the human wrote OUTSIDE the anchors is kept
as is, including a tail written right under another section.

Usage:
    open_questions.py --story 5-3 --title "transfers as internal" \\
        --spec _bmad-output/implementation-artifacts/spec-5-3-....md \\
        --commit a1b2c3d [--status done|blocked] [--repo .]  < items.md
    open_questions.py --story 5-3 --none --repo .      # no questions, no section needed

Always prints JSON to stdout. Exit 0 — the file is written, 1 — call error,
2 — not done by rule (a human wrote the file; nothing to remove).
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date

from common import (ARTIFACTS, QUESTIONS_MARKER, SPRINT_REL, STORY_NUM, key_story, norm_num,
                    num_order, parse_story, questions_file)
from plan_run import read_status

OPEN = re.compile(rf"^<!--\s*story:(\d+)-({STORY_NUM})\s*-->\s*$", re.M)
ANCHOR = re.compile(rf"^<!--\s*/?story:\d+-{STORY_NUM}\s*-->\s*$", re.M)
# Anchors are written with the normalized number; a hand-edited "story:2-6A" still matches.
UPDATED = re.compile(r"^\*\*Updated:\*\*.*$", re.M)
NO_COMMIT = ("none", "no", "-")

PREAMBLE = """# Epic {epic} — open questions

{marker}

What needs a human decision in the stories of this epic. The `auto-bmad` skill adds a
section here at the end of every story and fixes none of it itself: you decide the scope.
Stories closed without questions do not appear here — the counter below shows them.

A story section is the block between a pair of `story:<id>` service marks; a rerun of the
same story overwrites it whole. Everything written outside such blocks is kept untouched —
put your notes between sections, not inside them.

{updated}
"""


def epic_story_count(repo, epic):
    """How many stories the epic has in sprint-status.yaml. Not readable — None."""
    entries, err = read_status(os.path.join(repo, SPRINT_REL))
    if err:
        return None
    total = 0
    for key, _ in entries:
        ks = key_story(key)
        if ks and ks[0] == epic and not key.endswith("-retrospective"):
            total += 1
    return total or None


def split_sections(text):
    """File → (head, [(epic, num, section block, tail after it)], unclosed ids).

    The tail is the text between a section's closing anchor and the next section: the
    human's notes live there and move together with the section they are written under.
    No closing anchor (the file was edited by hand) — everything up to the next section
    counts as the section, and its id goes to unclosed: a rerun of that story would
    overwrite what is written under it, and the skill must tell the human.
    """
    opens = list(OPEN.finditer(text))
    if not opens:
        return text, [], []
    head = text[:opens[0].start()]
    sections, unclosed = [], []
    for i, m in enumerate(opens):
        epic, raw = int(m.group(1)), m.group(2)
        num = norm_num(raw)
        end = opens[i + 1].start() if i + 1 < len(opens) else len(text)
        chunk = text[m.start():end]
        close = chunk.find(f"<!-- /story:{m.group(1)}-{raw} -->")
        if close == -1:
            sections.append((epic, num, chunk.strip(), ""))
            unclosed.append(f"{epic}-{num}")
        else:
            cut = close + len(f"<!-- /story:{m.group(1)}-{raw} -->")
            sections.append((epic, num, chunk[:cut].strip(), chunk[cut:].strip()))
    return head, sections, unclosed


def closing(epic, num):
    return f"<!-- /story:{epic}-{num} -->"


def build_section(epic, num, title, spec_rel, commit, blocked, body):
    """One story block: anchor, heading, links line, the items."""
    head = f"## Story {epic}-{num}"
    if title:
        head += f" — {title}"
    if blocked:
        head += " (blocked)"
    links = []
    if spec_rel:
        name = os.path.basename(spec_rel).replace("%20", " ")
        links.append(f"Spec: [{name}]({spec_rel})")
    commit = (commit or "").strip("` ")
    if commit and commit.lower() not in NO_COMMIT:
        links.append(f"commit `{commit}`")
    elif blocked:
        links.append("no commit")
    lines = [f"<!-- story:{epic}-{num} -->", head, ""]
    if links:
        lines += [" · ".join(links), ""]
    lines += [body.strip(), "", closing(epic, num)]
    return "\n".join(lines)


def build_head(epic, existing_head, sections_count, total):
    """Head: a new file gets the whole preamble, an existing one only new counters."""
    counters = [f"**Updated:** {date.today().isoformat()}"]
    if total:
        counters.append(f"**stories in the epic:** {total}")
    counters.append(f"**with open questions:** {sections_count}")
    updated = " · ".join(counters)

    if existing_head is None:
        return PREAMBLE.format(epic=epic, marker=QUESTIONS_MARKER.format(epic=epic), updated=updated)
    if UPDATED.search(existing_head):
        return UPDATED.sub(lambda _: updated, existing_head, count=1)
    return existing_head.rstrip() + "\n\n" + updated + "\n"


def rel_spec(spec, directory, repo):
    """The spec link relative to the artifacts folder, where the spec lives.

    Returns (link, warning). Two pitfalls:

    * Both ends need `realpath`: macOS returns `getcwd()` resolved (`/private/tmp`), the
      incoming absolute path is not, and on a symlink the link becomes `../../../../var/…`.
    * A spec from a parallel run may live in the story's worktree, which `worktree.py prune`
      removes. So never link outside the artifacts folder — keep the bare file name.
    """
    spec = spec.strip()
    if not spec:
        return "", None
    if not os.path.isabs(spec) and not os.path.exists(spec):
        candidate = os.path.join(repo, spec)
        if os.path.exists(candidate):
            spec = candidate
    rel = os.path.relpath(os.path.realpath(spec), os.path.realpath(directory))
    name = os.path.basename(spec)
    if rel.startswith(".."):
        return name.replace(" ", "%20"), (
            f"spec {spec} is outside the artifacts folder (a worktree?) — "
            f"the link keeps only the file name {name}")
    return rel.replace(" ", "%20"), None


def write_atomic(path, text):
    """Writes through a temporary file next to it: a broken write must not lose the whole epic."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".open-questions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def fail(code, message, path=None, changed=False):
    print(message, file=sys.stderr)
    payload = {"error": message, "changed": changed}
    if path:
        payload["path"] = os.path.abspath(path)
    print(json.dumps(payload, ensure_ascii=False))
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True, help="story id: 5-3")
    ap.add_argument("--title", default="", help="story title in plain language")
    ap.add_argument("--spec", default="", help="path to the story spec")
    ap.add_argument("--commit", default="", help="engine commit hash")
    ap.add_argument("--status", default="done", choices=("done", "blocked"))
    ap.add_argument("--none", dest="empty", action="store_true",
                    help="the story has no open questions — no section needed")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    parsed = parse_story(args.story)
    if not parsed:
        return fail(1, f"cannot parse the story id: {args.story!r}")
    epic, num = parsed

    directory = os.path.join(args.repo, ARTIFACTS)
    if not os.path.isdir(directory):
        return fail(1, f"missing folder {directory}")
    rel_path = questions_file(epic)
    path = os.path.join(args.repo, rel_path)

    body = "" if args.empty else sys.stdin.read().strip()
    if ANCHOR.search(body) or "<!-- auto-bmad:open-questions" in body:
        return fail(1, "the items contain a section service anchor — remove it",
                    path=path)

    warnings = []
    existing_head, sections = None, []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if QUESTIONS_MARKER.format(epic=epic) not in text:
            return fail(2, f"a human wrote {path} (no auto-bmad marker) — "
                           "left untouched", path=path)
        existing_head, sections, unclosed = split_sections(text)
        if unclosed:
            warnings.append(
                "sections " + ", ".join(unclosed) + " have no closing mark: "
                "what is written under them counts as part of the section and a rerun "
                "of that story will overwrite it")

    index = next((i for i, s in enumerate(sections) if (s[0], s[1]) == (epic, num)), None)
    keep = [s for s in sections if (s[0], s[1]) != (epic, num)]

    if not body:
        if index is None:
            return fail(2, f"story {epic}-{num} has no questions and had no section — "
                           "the file is untouched", path=path, changed=False)
        action = "removed"
        # The removed section's tail holds the human's notes: move it under the previous section or into the head.
        tail = sections[index][3]
        if tail and index > 0:
            prev = sections[index - 1]
            keep[index - 1] = (prev[0], prev[1], prev[2],
                               (prev[3] + "\n\n" + tail).strip())
        elif tail:
            existing_head = (existing_head or "").rstrip() + "\n\n" + tail + "\n"
    else:
        action = "updated" if index is not None else "added"
        link, warning = rel_spec(args.spec, directory, args.repo)
        if warning:
            warnings.append(warning)
        block = build_section(epic, num, args.title.strip(), link,
                              args.commit.strip(), args.status == "blocked", body)
        keep.append((epic, num, block, sections[index][3] if index is not None else ""))

    keep.sort(key=lambda s: (s[0], num_order(s[1])))
    head = build_head(epic, existing_head, len(keep), epic_story_count(args.repo, epic))
    body_out = "\n\n".join(
        block + ("\n\n" + tail if tail else "") for _, _, block, tail in keep)
    out = head.rstrip() + "\n\n" + body_out

    write_atomic(path, out.rstrip() + "\n")

    result = {
        "path": os.path.abspath(path),
        "questions_file": rel_path,
        "epic": epic,
        "story": f"{epic}-{num}",
        "action": action,
        "sections": len(keep),
        "changed": True,
        "warnings": warnings,
        "error": None,
    }
    for warning in warnings:
        print(warning, file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
