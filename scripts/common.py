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


REV = re.compile(r"^[0-9a-fA-F]{4,64}$")
CODE = (".", ":(exclude)_bmad-output")
REVIEW_LATER = ("in review, but other work was committed after it: the engine would review that "
                "work too — review it by hand, or move it to another status")


def spec_index(repo):
    """{(epic, number): [spec paths]} of every story spec, from one directory listing."""
    out = {}
    for path in sorted(glob.glob(os.path.join(repo, ARTIFACTS, "spec-*.md"))):
        m = SPEC_RE.match(os.path.basename(path))
        if m:
            out.setdefault((int(m.group(1)), norm_num(m.group(2))), []).append(path)
    return out


def frontmatter(path):
    """Flat YAML frontmatter parse: top-level scalars plus list sizes."""
    fields, lists, current = {}, {}, None
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if not lines or lines[0].strip() != "---":
        return fields, lists
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t")):
            if current and line.strip().startswith("- "):
                lists[current] = lists.get(current, 0) + 1
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        current = key if not value else None
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            lists[key] = len([x for x in inner.split(",") if x.strip()]) if inner else 0
            current = None
        elif value:
            fields[key] = value.strip("'\"")
    return fields, lists


def baseline(fields):
    """The spec's baseline revision; older engine versions wrote `baseline_commit`."""
    return (fields.get("baseline_revision") or fields.get("baseline_commit") or "").strip()


def story_commits(path, repo, fields):
    """The story's engine commits since the spec's baseline (merge commits do not count).

    → {"first", "last", "files", "later"}: the engine commits the spec together with the code,
    so its commits are those that changed both. `first` — the earliest (a later edit of the
    spec by other work does not move it), `last` — the newest (a fix run of the story),
    `files` — the files in `last`, `later` — code commits after `first` that are not the
    story's. No such commit (the spec is not under git, or was committed apart from the code) —
    `last` is the last commit that changed code, `first` and `later` are None. No baseline —
    all None.
    """
    out = {"first": None, "last": None, "files": None, "later": None}
    base = baseline(fields)
    if not REV.match(base):
        return out
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(repo))
    log = git(repo, "log", "--no-merges", "--reverse", "--full-diff", "--name-only", "--format=@%h",
              f"{base}..HEAD", "--", rel)
    own, names = [], {}
    for line in (log.stdout if log.returncode == 0 else "").splitlines():
        if line.startswith("@"):
            own.append(line[1:])
            names[own[-1]] = []
        elif line.strip() and own:
            names[own[-1]].append(line.strip())
    engine = [sha for sha in own if any(not n.startswith("_bmad-output/") for n in names[sha])]
    if engine:
        out["first"], out["last"] = engine[0], engine[-1]
        out["files"] = len(names[engine[-1]])
        later = git(repo, "log", "--no-merges", "--format=%h", f"{engine[0]}..HEAD", "--", *CODE)
        out["later"] = len([sha for sha in later.stdout.split() if sha not in own]) \
            if later.returncode == 0 else None
        return out
    last = git(repo, "log", "-1", "--no-merges", "--name-only", "--format=@%h", f"{base}..HEAD", "--", *CODE)
    lines = [x for x in last.stdout.splitlines() if x.strip()] if last.returncode == 0 else []
    if lines:
        out["last"] = lines[0][1:]
        shown = git(repo, "show", "--name-only", "--format=", out["last"])
        out["files"] = len([x for x in shown.stdout.splitlines() if x.strip()])
    return out


def review_skips(entries, repo):
    """{(epic, number): reason} of the review stories the run must not take.

    No spec — written outside the engine, nothing to review against. A done spec with other
    work committed after the story — the engine reviews everything since the baseline.
    """
    out, index = {}, None
    for key, value in entries:
        ks = key_story(key)
        if value != "review" or not ks:
            continue
        index = spec_index(repo) if index is None else index
        specs = index.get(ks[:2], [])
        if not specs:
            out[ks[:2]] = ("in review but has no spec (written outside the engine): the engine "
                           "reviews only against a spec — review it by hand")
        elif len(specs) == 1:
            fields, _ = frontmatter(specs[0])
            if fields.get("status") == "done" and story_commits(specs[0], repo, fields)["later"]:
                out[ks[:2]] = REVIEW_LATER
    return out


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


def main_tree(repo):
    """The main working tree of the repository; for a linked worktree — the tree that owns it.

    Run state that must outlive a worktree (statistics, the event journal) is kept there.
    Not a git repository — the path itself.
    """
    proc = git(repo, "worktree", "list", "--porcelain")
    first = proc.stdout.split("\n\n", 1)[0].splitlines() if proc.returncode == 0 else []
    if not first or not first[0].startswith("worktree ") or "bare" in first[1:]:
        return os.path.abspath(repo)
    return first[0].split(" ", 1)[1]


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

