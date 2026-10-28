"""Paths and ids shared by the auto-bmad scripts."""

import glob
import os
import re
import subprocess

ARTIFACTS = os.path.join("_bmad-output", "implementation-artifacts")
PLANNING = os.path.join("_bmad-output", "planning-artifacts")
SPRINT_REL = os.path.join(ARTIFACTS, "sprint-status.yaml")
QUESTIONS_NAME = "epic-{epic}-open-questions.md"
QUESTIONS_MARKER = "<!-- auto-bmad:open-questions epic={epic} -->"


def questions_file(epic):
    """Path of the epic's open questions file, relative to the repo."""
    return os.path.join(ARTIFACTS, QUESTIONS_NAME.format(epic=epic))


# A story number as in BMad's sprint-status keys: digits and an optional split letter
# ("3", "6a"); the key is "<epic>-<number>-<slug>" (bmad-sprint-planning/scripts/sprint_plan.py).
STORY_NUM = r"\d+[a-zA-Z]?"
STORY_KEY = re.compile(rf"^(\d+)-({STORY_NUM})-(.+)$")


def norm_num(raw):
    """A story number in one form: "06A" → "6a". Not a story number — None."""
    m = re.fullmatch(r"(\d+)([a-zA-Z]?)", (raw or "").strip())
    return f"{int(m.group(1))}{m.group(2).lower()}" if m else None


def key_story(key):
    """sprint-status key → (epic, story number, slug), the number normalized; not a story — None."""
    m = STORY_KEY.match(key)
    if not m:
        return None
    return int(m.group(1)), norm_num(m.group(2)), m.group(3)


# A story spec of the engine: spec-<epic>-<number>-<slug>.md in the implementation artifacts.
SPEC_RE = re.compile(rf"^spec-(\d+)-({STORY_NUM})-(.*)\.md$", re.I)


def is_story_spec(name, epic, num):
    """Is this file name a spec of story <epic>-<num>? Numbers compare as numbers: 1-1 is not 1-10."""
    m = SPEC_RE.match(name)
    return bool(m and int(m.group(1)) == epic and norm_num(m.group(2)) == num)


def story_specs(repo, epic, num):
    """Paths of the story's specs, sorted; none — []."""
    return [p for p in sorted(glob.glob(os.path.join(repo, ARTIFACTS, "spec-*.md")))
            if is_story_spec(os.path.basename(p), epic, num)]


def num_order(num):
    """Sort key of a story number: "6" < "6a" < "6b" < "7"; anything else sorts last."""
    m = re.fullmatch(r"(\d+)([a-z]?)", num or "")
    return (int(m.group(1)), m.group(2)) if m else (float("inf"), num or "")


def parse_story(value):
    """`5-3`, `5.3` or `2-6a` → (5, "3") / (2, "6a"). Not parsed — None."""
    m = re.match(r"^(\d+)[.\-](\d+[a-zA-Z]?)$", (value or "").strip())
    return (int(m.group(1)), norm_num(m.group(2))) if m else None


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def commit_paths(repo, paths, message):
    """Stage and commit exactly these paths → (sha or None, error or None).

    Missing paths are skipped; nothing staged after `add` — (None, None), no commit.
    """
    paths = [p for p in dict.fromkeys(paths) if os.path.exists(os.path.join(repo, p))]
    if not paths:
        return None, None
    add = git(repo, "add", "--", *paths)
    if add.returncode:
        return None, (add.stderr or add.stdout).strip()[:300]
    if not git(repo, "diff", "--cached", "--quiet", "--", *paths).returncode:
        return None, None
    proc = git(repo, "commit", "-q", "-m", message, "--", *paths)
    if proc.returncode:
        return None, (proc.stderr or proc.stdout).strip()[:300]
    return git(repo, "rev-parse", "HEAD").stdout.strip(), None

