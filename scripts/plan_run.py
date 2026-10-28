#!/usr/bin/env python3
"""Parses the auto-bmad run argument and builds the story queue.

Compares epic numbers as numbers (otherwise `1-*` matches `11-*`), drops
`epic-N-retrospective`, orders the stories and picks the default story.
Also returns the run language (BMad `communication_language`) and the path of the
epic's open questions file.

Usage:
    plan_run.py --arg "epic-1 --parallel-fast 4" [--repo .]
    plan_run.py --arg "epic-1 --width 4"
    plan_run.py --arg "epic-1 --no-parallel"
    plan_run.py --arg ""            # the default story

Checks the epic's "Waits" line in epics.md against sprint-status.yaml: an unmet
condition on the whole epic gives `error` and `waiting`; one on a single story cuts
the queue before that story, with the reason in `note`.

Prints JSON to stdout. Exit 0 — parsed, 1 — read error, 2 — the argument is
ambiguous (`error` in JSON, the model must ask the human) or the epic waits for an
unmet condition (`waiting` — nothing to ask, the run does not start).
"""

import argparse
import glob
import json
import os
import re
import sys

from common import (ARTIFACTS, PLANNING, QUESTIONS_MARKER, SPRINT_REL,  # noqa: F401 (re-exported)
                    key_story, norm_num, num_order, questions_file, story_specs)

LEVELS = ("fast", "normal", "deep")
# epics.md headings: the grammar of BMad's own parser (bmad-sprint-planning/scripts/sprint_plan.py,
# BMad 6.12), which builds sprint-status.yaml from the same file. The keywords are English
# ("## Epic 2: …", "### Story 2.3: …"); the title may be in any language. Fenced code is skipped.
EPIC_RE = re.compile(r"^#{1,3}\s*Epic\s+(\d+)\s*:?\s*(.*?)\s*#*\s*$", re.I)
STORY_RE = re.compile(r"^#{2,4}\s*Story\s+(\d+)\.(\d+[a-z]?)\s*:?\s*(.*?)\s*#*\s*$", re.I)
FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")
SECTION_END = re.compile(r"^#{1,3}\s")
# A numbered heading outside that grammar ("## Épica 2: …", "### Phase 1.2: …"): reported, not read.
NUMBERED_HEAD = re.compile(r"^#{1,4}\s*[^\W\d_]+\s+\d+(?:\.\d+[a-z]?)?\s*[:.]")
# "I want, …" / "**I want** to …" / "- I want …" — what the story does, for the run table.
WANT = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?I want(?:\*\*)?[,:]?\s+(?:to\s+)?(.+?)\s*$", re.M)
# User story template lines that do not say what is done.
NOT_GOAL = re.compile(r"^(?:[-*]\s+)?(?:\*\*)?(?:As an?|So that)\b", re.I)
# A service tag at the end of an epic heading ("[deferred 2026-10-05]") is dropped.
EPIC_TAG = re.compile(r"\s*\[[^\]]*\]\s*$")
GOAL_MAX = 110
# Epic dependencies: a "**Waits:** …" line under the epic heading, both in the Epic List
# (`### Epic N`) and in the epic section (`## Epic N`).
WAITS_LINE = re.compile(r"^\s*(?:[-*]\s+)?\*{0,2}(?:Waits(?:\s+for)?|Depends\s+on)\*{0,2}\s*:"
                        r"\s*\*{0,2}\s*(.+?)\s*$", re.M | re.I)
# "20.5–20.7, 20.9 — epic 14": the condition applies to these stories only.
STORY_ITEM = r"\d+\.\d+[a-z]?(?:\s*[–-]\s*\d+\.\d+[a-z]?)?"
SCOPED = re.compile(rf"^\s*({STORY_ITEM}(?:\s*(?:,|\band\b)\s*{STORY_ITEM})*)\s*—\s*(.+)$", re.I)
WAIT_TOKEN = re.compile(r"(epics?\b)|(stor(?:y|ies)\b)|(\d+)\.(\d+[a-z]?)(?![a-z])|(\d+)", re.I)
WAIT_FILLER = re.compile(r"\band\b|[,.\s]", re.I)


def epics_file(repo):
    for p in (os.path.join(repo, PLANNING, "epics.md"), *sorted(glob.glob(os.path.join(repo, PLANNING, "*epic*.md")))):
        if os.path.isfile(p):
            return p
    return None


def outside_fences(text):
    """The lines of the document with fenced code blocks blanked out, as BMad's parser skips them."""
    out, in_fence = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
        else:
            out.append("" if in_fence else line)
    return out


def section(lines, i):
    """Lines after heading i up to the next heading of level 1–3."""
    end = next((j for j in range(i + 1, len(lines)) if SECTION_END.match(lines[j])), len(lines))
    return lines[i + 1:end]


def clean_title(raw):
    return EPIC_TAG.sub("", raw.lstrip(":.—–- ")).strip()


def parse_epics(text):
    """→ ({N: epic title}, {(N, "M"): (title, section text)}); M is a story number ("3", "6a")."""
    lines = outside_fences(text)
    epics, stories = {}, {}
    for i, line in enumerate(lines):
        m = EPIC_RE.match(line)
        if m:
            if clean_title(m.group(2)):
                epics[int(m.group(1))] = clean_title(m.group(2))
            continue
        m = STORY_RE.match(line)
        if m:
            stories[(int(m.group(1)), norm_num(m.group(2)))] = (m.group(3), "\n".join(section(lines, i)).strip())
    return epics, stories


def heading_warnings(text):
    """Numbered headings that BMad's grammar does not read — one warning with the first of them."""
    bad = [(n, line.strip()) for n, line in enumerate(outside_fences(text), 1)
           if NUMBERED_HEAD.match(line) and not EPIC_RE.match(line) and not STORY_RE.match(line)]
    if not bad:
        return []
    n, first = bad[0]
    return [f"{len(bad)} numbered heading(s) are not in BMad's format \"## Epic N: …\" / "
            f"\"### Story N.M: …\" (English keywords, any title) and are not read as epics or "
            f"stories; the first, line {n}: \"{first[:70]}\""]


def story_goal(body):
    """What the story does — the "I want" line or the first meaningful line, for the table."""
    m = WANT.search(body)
    if m:
        line = m.group(1)
    else:
        line = next((ln.strip() for ln in body.splitlines()
                     if ln.strip() and not NOT_GOAL.match(ln.strip())), "")
    # A markdown table cell: "|" would split the row into extra columns.
    line = line.rstrip(",.;").replace("|", "/")
    if not line:
        return None
    return line if len(line) <= GOAL_MAX else line[:GOAL_MAX - 1].rstrip() + "…"


def load_epics(repo):
    """Epic and story titles for the run table.

    The table is cosmetic and plan_run is the first step of the run: an unreadable
    epics.md must not fail it, only leave titles from slugs (a warning).
    """
    path = epics_file(repo)
    if not path:
        return {}, {}, None
    try:
        with open(path, encoding="utf-8") as fh:
            epics, stories = parse_epics(fh.read())
    except (OSError, UnicodeDecodeError) as exc:
        return {}, {}, f"{path} is not readable ({exc}) — the run table uses titles from slugs"
    return epics, stories, None


def epic_sections(text):
    """[(N, lines of the section)] for every epic heading, in the Epic List and in the epic itself."""
    lines = outside_fences(text)
    return [(int(m.group(1)), section(lines, i))
            for i, m in ((i, EPIC_RE.match(line)) for i, line in enumerate(lines)) if m]


def parse_waits(text):
    """→ {N: [epic N "Waits" line, …]} — without repeats from the Epic List and the epic section."""
    out = {}
    for n, body in epic_sections(text):
        for w in WAITS_LINE.finditer("\n".join(body)):
            line = w.group(1).strip().strip("*").strip()
            lst = out.setdefault(n, [])
            if line and line not in lst:
                lst.append(line)
    return out


def story_items(scope):
    """"20.5–20.7, 20.9, 2.6a–2.6c" → [(20, "5", "7"), (20, "9", "9"), (2, "6a", "6c")].

    Each item is a range of one epic, ends included; covers() tells whether a story is in it.
    A range whose ends are in different epics counts as its first story only.
    """
    out = []
    for m in re.finditer(r"(\d+)\.(\d+[a-z]?)(?:\s*[–-]\s*(\d+)\.(\d+[a-z]?))?", scope, re.I):
        e, lo = int(m.group(1)), norm_num(m.group(2))
        hi = norm_num(m.group(4)) if m.group(3) and int(m.group(3)) == e else lo
        if num_order(hi) < num_order(lo):
            lo, hi = hi, lo
        out.append((e, lo, hi))
    return out


def covers(items, epic, num):
    """Is story epic.num inside one of the story_items() ranges: 2.5–2.7 covers 2.6 and 2.6a."""
    return any(e == epic and num_order(lo) <= num_order(num) <= num_order(hi) for e, lo, hi in items)


def parse_wait_clauses(line):
    """A "Waits" line → conditions: {"text", "stories", "epics", "story_refs", "free"}.

    stories — which stories the condition is for (None — the whole epic); epics and
    story_refs — what to wait for; free — a condition the script cannot check (text as is).
    """
    clauses = []
    # ";" inside a parenthesised note does not split conditions.
    for raw in re.split(r";(?![^()]*\))", line.rstrip(".")):
        raw = raw.strip()
        if not raw:
            continue
        target, stories = raw, None
        m = SCOPED.match(re.sub(r"\([^)]*\)", "", raw))
        if m:
            stories = story_items(m.group(1))
            # The target comes from the original line, with the parentheses: the human needs the note.
            target = raw.split("—", 1)[1].strip()
        bare = re.sub(r"\([^)]*\)", "", target)
        epics, refs, kind, free = [], [], None, False
        for t in WAIT_TOKEN.finditer(bare):
            if t.group(1):
                kind = "epic"
            elif t.group(2):
                kind = "story"
            elif t.group(3):
                refs.append((int(t.group(3)), norm_num(t.group(4))))
            elif kind == "epic":
                epics.append(int(t.group(5)))
            else:
                free = True
        # Anything left besides references and conjunctions is a condition in words: not checkable.
        if WAIT_FILLER.sub("", WAIT_TOKEN.sub("", bare)) or not (epics or refs):
            free = True
        clauses.append({"text": raw, "stories": stories, "epics": epics,
                        "story_refs": refs, "free": target if free else None})
    return clauses


def unmet(clause, status, epic, own=False):
    """What in the condition is not met → lines for the human. Empty — the condition is met.

    References inside the own epic (own=False) are not checked: in an epic run the order
    by number already holds them, the earlier story is done before the one that waits.
    A single story run (own=True) has no such guarantee, so there they are checked.
    """
    if clause["free"]:
        return [f'"{clause["free"]}" — cannot check, the owner decides']
    out = []
    for n in clause["epics"]:
        value = status.get(f"epic-{n}")
        if (own or n != epic) and value != "done":
            out.append(f"epic {n} ({value or 'not in sprint-status'})")
    for e, s in clause["story_refs"]:
        if e == epic and not own:
            continue
        value = next((v for k, v in status.items() if (ks := key_story(k)) and ks[:2] == (e, s)), None)
        if value != "done":
            out.append(f"story {e}.{s} ({value or 'not in sprint-status'})")
    return out


def waits_for(clauses, status, epic, story=None, own=False):
    """Unmet conditions: for the whole epic (story=None) or for one of its stories."""
    out = []
    for c in clauses:
        if story is None and c["stories"] is not None:
            continue
        if story is not None and (c["stories"] is None or not covers(c["stories"], epic, story)):
            continue
        out.extend(u for u in unmet(c, status, epic, own) if u not in out)
    return out


def load_waits(repo):
    """{N: [epic N conditions]} from epics.md. An unreadable file — empty: load_epics already warned."""
    path = epics_file(repo)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = parse_waits(fh.read())
    except (OSError, UnicodeDecodeError):
        return {}
    return {n: [c for line in ls for c in parse_wait_clauses(line)] for n, ls in lines.items()}


def load_heading_warnings(repo):
    """heading_warnings() of the project's epics.md; an unreadable file — none."""
    path = epics_file(repo)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        return heading_warnings(text)
    except (TypeError, OSError, UnicodeDecodeError):
        return []


def read_status(path):
    """Flat parse of development_status without external dependencies."""
    if not os.path.exists(path):
        return None, f"not found: {path}"
    entries = []
    inside = False
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith((" ", "\t")):
                inside = line.split(":", 1)[0].strip() == "development_status"
                continue
            if not inside or ":" not in line:
                continue
            key, _, value = line.strip().partition(":")
            entries.append((key.strip(), value.split("#", 1)[0].strip().strip("'\"")))
    if not entries:
        return None, f"{path} has no non-empty development_status section"
    return entries, None


def take_number(tokens, i, inline):
    """The flag's number: from `--flag=N` or from the next token. Returns (number, new i)."""
    if inline:
        return inline, i
    if i + 1 < len(tokens) and tokens[i + 1].isdigit():
        return tokens[i + 1], i + 1
    return "", i


RUN_PARALLEL = ("conservative", "aggressive", "off")


def load_config(repo):
    """The merged auto-bmad config, or {} when it cannot be read."""
    try:
        from ext import load
        cfg, _, _ = load(repo)
    except Exception:  # a broken config or no ext: the run goes on built-in defaults
        return {}
    return cfg


def run_section(cfg):
    return cfg.get("run", {}) if isinstance(cfg.get("run"), dict) else {}


def run_defaults(repo, cfg=None):
    """Run defaults from the config's [run] section (level, parallel, width); setup writes them."""
    run = run_section(load_config(repo) if cfg is None else cfg)
    out = {}
    if run.get("level") in LEVELS:
        out["level"] = run["level"]
    if run.get("parallel") in RUN_PARALLEL:
        out["parallel"] = run["parallel"]
    if isinstance(run.get("width"), int) and run["width"] > 0:
        out["width"] = run["width"]
    return out


# BMad config files from the highest priority down, as BMad's load_central_config merges them:
# the first non-empty communication_language wins.
LANGUAGE_FILES = (
    os.path.join("_bmad", "custom", "config.user.toml"),
    os.path.join("_bmad", "custom", "config.toml"),
    os.path.join("_bmad", "config.user.toml"),
    os.path.join("_bmad", "config.toml"),
    os.path.join("_bmad", "core", "config.yaml"),
    os.path.join("_bmad", "bmm", "config.yaml"),
)
YAML_LANGUAGE = re.compile(r"^communication_language\s*:\s*(.*?)\s*$", re.M)


def toml_language(data):
    """communication_language from a BMad TOML config: [core] first, then the top level."""
    for table in (data.get("core"), data):
        value = table.get("communication_language") if isinstance(table, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def bmad_language(repo):
    """The run language: BMad communication_language, or None when no config sets it."""
    for rel in LANGUAGE_FILES:
        path = os.path.join(repo, rel)
        if not os.path.isfile(path):
            continue
        try:
            if path.endswith(".toml"):
                import tomllib
                with open(path, "rb") as fh:
                    value = toml_language(tomllib.load(fh))
            else:
                with open(path, encoding="utf-8") as fh:
                    m = YAML_LANGUAGE.search(fh.read())
                value = m.group(1).split(" #", 1)[0].strip().strip("'\"") if m else None
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if value:
            return value
    return None


def parse_flags(arg, defaults=None):
    """Takes out the level and parallel flags. Flags win over the [run] config defaults.

    Returns (level, parallel, width, scope, error, warnings). Parallel is always on in
    Epic mode: there is no separate "turn on" switch. `--parallel-fast` makes story
    selection aggressive, `--no-parallel` turns parallel off, `--width N` (or a number
    after --parallel-fast) sets the wave width.
    """
    tokens = (arg or "").split()
    defaults = defaults or {}
    level, rest, error = None, [], None
    parallel, width = defaults.get("parallel", "conservative"), defaults.get("width", 3)
    warnings = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower().lstrip("-")
        base, _, inline = low.partition("=")
        if tok.startswith("--") and base == "parallel":
            # A removed flag must not go silent: in scope it would still match "epic-1"
            # and the run would start with width 3 instead of the requested one.
            num, i = take_number(tokens, i, inline)
            if num.isdigit() and int(num) > 0:
                width = int(num)
                warnings.append(f"--parallel is removed: parallel is on by default and "
                                f"the width is set with --width N — took {width} as the width")
            else:
                warnings.append("--parallel is removed: in Epic mode parallel is on "
                                "by default, there is no separate switch to turn it on")
        elif tok.startswith("--") and base in LEVELS:
            if level and level != base:
                error = f"two different levels in the argument: {level} and {base}"
            level = base
        elif tok.startswith("--") and base in ("no-parallel", "noparallel", "sequential"):
            parallel = "off"
        elif tok.startswith("--") and base in ("parallel-fast", "parallel_fast"):
            parallel = "aggressive"
            num, i = take_number(tokens, i, inline)
            if num.isdigit() and int(num) > 0:
                width = int(num)
        elif tok.startswith("--") and base == "width":
            num, i = take_number(tokens, i, inline)
            if num.isdigit() and int(num) > 0:
                width = int(num)
            else:
                error = "--width needs a positive number"
        else:
            rest.append(tok)
        i += 1
    return (level or defaults.get("level", "normal"), parallel, width, " ".join(rest).strip(),
            error, warnings)


def parse_scope(scope, entries, waits=None, no_spec=None):
    """Finds the mode and the target: epic-N, story N-M or the default pick."""
    if not scope:
        return default_story(entries, waits, no_spec)

    low = scope.lower()
    # Story first: a pair of numbers is unambiguous, and an epic mentioned next to it
    # ("story 3-7 of epic 3") must not turn one story into a whole epic run.
    m = re.search(r"(?<!\d)(\d+)[.\-](\d+[a-z]?)(?!\w)", low)
    if m:
        return {"mode": "story", "epic": int(m.group(1)), "story": norm_num(m.group(2))}, None

    # One word and one number ("epic-7", "epic 7", the same word in another language) or a
    # bare number — an epic. Anything else is not guessed: "story 7" or "fix bug 12" go to the human.
    m = re.match(r"^\s*(?:([^\W\d_]+)[\s-]*)?(\d+)\s*$", low)
    if m and m.group(1) not in ("story", "stories"):
        return {"mode": "epic", "epic": int(m.group(2)), "story": None}, None

    return None, f"cannot parse the scope argument: {scope!r}"


def default_story(entries, waits=None, no_spec=None):
    """The first in-progress story, else review, else ready-for-dev, else the first backlog of an in-progress epic.

    Skips a backlog story that waits for an unmet condition (the epic's "Waits"): without
    an argument the human did not pick the epic and must not hit someone else's dependency.
    Started stories (in-progress, review, ready-for-dev) are taken as is, except a review story
    without a spec (`no_spec`, {(epic, number)}): the engine cannot review it.
    """
    waits = waits or {}
    no_spec = no_spec or set()
    status = dict(entries)

    def blocked(e, s):
        c = waits.get(e, [])
        return waits_for(c, status, e) + waits_for(c, status, e, s, own=True)

    stories = [(key_story(k), v) for k, v in entries if key_story(k)]
    review_note = None
    for wanted in ("in-progress", "review", "ready-for-dev"):
        for (e, s, _), value in stories:
            if value == "review" and (e, s) in no_spec:
                review_note = review_note or skip_review_note(f"{e}-{s}")
                continue
            if value == wanted:
                target = {"mode": "story", "epic": e, "story": s}
                if review_note:
                    target["note"] = review_note
                return target, None
    active = {int(k.split("-")[1]) for k, v in entries
              if k.startswith("epic-") and v == "in-progress" and k.split("-")[1].isdigit()}
    backlog = []
    skipped = []
    for (e, s, _), value in stories:
        if value != "backlog":
            continue
        why = blocked(e, s)
        if why:
            skipped.append(f"{e}-{s} waits for: {'; '.join(why)}")
        else:
            backlog.append((e, s))
    skip_note = ('skipped stories with an unmet "Waits": ' + " | ".join(skipped[:5])
                 + (f" and {len(skipped) - 5} more" if len(skipped) > 5 else "")) if skipped else None
    if review_note:
        skip_note = f"{review_note}; {skip_note}" if skip_note else review_note
    for e, s in backlog:
        if e in active:
            target = {"mode": "story", "epic": e, "story": s}
            if skip_note:
                target["note"] = skip_note
            return target, None
    # No unfinished stories left in in-progress epics: take the first backlog story at all.
    if backlog:
        e, s = backlog[0]
        note = "in-progress epics have no unfinished stories — took the first backlog story of the next epic"
        return {"mode": "story", "epic": e, "story": s,
                "note": f"{note}; {skip_note}" if skip_note else note}, None
    if skipped:
        return None, f"all backlog stories wait for unmet conditions: {skip_note}"
    if review_note:
        return None, f"no story to run: {review_note}"
    return None, "sprint-status.yaml has no unfinished stories"


def skip_review_note(story_id):
    return (f"story {story_id} is in review but has no spec (written outside the engine): "
            "skipped — the engine reviews only against a spec; review it by hand")


def story_entry(entries, epic, num):
    """The story's sprint-status key and status; not there — (None, None)."""
    for key, value in entries:
        ks = key_story(key)
        if ks and ks[:2] == (epic, num):
            return key, value
    return None, None


def specless_reviews(entries, repo):
    """{(epic, number)} of the review stories that have no spec."""
    out = set()
    for key, value in entries:
        ks = key_story(key)
        if value == "review" and ks and not story_specs(repo, ks[0], ks[1]):
            out.add(ks[:2])
    return out


def collect(entries, epic, only_story=None, story_text=None):
    """Epic stories in number order: not done, no retrospective.

    title and goal come from epics.md, so the run table speaks plain language;
    a story missing there gets the title from its slug and an empty goal.
    """
    story_text = story_text or {}
    out = []
    for key, value in entries:
        ks = key_story(key)
        if not ks or ks[0] != epic:
            continue
        if key.endswith("-retrospective") or value == "done":
            continue
        _, num, slug = ks
        if only_story is not None and num != only_story:
            continue
        title, body = story_text.get((epic, num), (None, ""))
        out.append({
            "key": key,
            "id": f"{epic}-{num}",
            "num": num,
            "status": value,
            "slug": slug,
            "title": (title or slug.replace("-", " ").strip()).replace("|", "/"),
            "goal": story_goal(body),
        })
    out.sort(key=lambda s: num_order(s["num"]))
    return out


def check_waits(result, clauses, status, epic, own=False):
    """Checks the queue against the epic's "Waits" line and edits result in place.

    A `review` story has its code written and waits for nothing: it always stays. An
    unmet condition on the whole epic — only the review stories go, none — error, the run
    does not start. On a single story — the queue is cut before it (order by number, no
    going past it), the reason is in note; nothing left to run — error. What is unmet goes
    to waiting.
    """
    ready = [s for s in result["stories"] if s["status"] == "review"]
    rest = [s for s in result["stories"] if s["status"] != "review"]
    whole = waits_for(clauses, status, epic)
    if whole and rest:
        result["waiting"] = whole
        if not ready:
            result["error"] = f"epic {epic} waits for unmet conditions: {'; '.join(whole)}"
            return
        result["stories"] = ready
        note = (f"epic {epic} waits for {'; '.join(whole)}: only the stories in review go, "
                f"their code is written. In the run: {', '.join(k['id'] for k in ready)}")
        result["note"] = f"{result['note']}; {note}" if result.get("note") else note
        return
    for i, s in enumerate(rest):
        why = waits_for(clauses, status, epic, s["num"], own)
        if not why:
            continue
        result["waiting"] = why
        kept = sorted(ready + rest[:i], key=lambda k: num_order(k["num"]))
        result["stories"] = kept
        if not kept:
            result["error"] = f"story {s['id']} waits for unmet conditions: {'; '.join(why)}"
        else:
            note = (f"the queue stops before story {s['id']}: it waits for {'; '.join(why)}. "
                    f"In the run: {', '.join(k['id'] for k in review_first(kept))}")
            result["note"] = f"{result['note']}; {note}" if result.get("note") else note
        return


def review_first(stories):
    """`review` stories at the head, each part in its own order: their code waits only for review."""
    return [s for s in stories if s["status"] == "review"] + [s for s in stories if s["status"] != "review"]


def skip_specless(result, no_spec):
    """Takes the review stories without a spec out of the queue → `skipped` and a note."""
    skipped = [s for s in result["stories"] if s["status"] == "review" and (result["epic"], s["num"]) in no_spec]
    if not skipped:
        return
    result["stories"] = [s for s in result["stories"] if s not in skipped]
    result["skipped"] = [{"id": s["id"], "title": s["title"],
                          "reason": "in review but has no spec (written outside the engine): the engine "
                                    "reviews only against a spec — review it by hand"} for s in skipped]
    note = "; ".join(skip_review_note(s["id"]) for s in skipped)
    result["note"] = f"{result['note']}; {note}" if result.get("note") else note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arg", default="", help="the skill argument string as is")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    path = os.path.join(args.repo, SPRINT_REL)
    entries, err = read_status(path)
    if err:
        print(err, file=sys.stderr)
        return 1

    cfg = load_config(args.repo)
    level, parallel, width, scope, flag_error, warnings = parse_flags(args.arg,
                                                                      run_defaults(args.repo, cfg))
    result = {
        "level": level,
        "parallel": parallel,
        "parallel_width": width,
        "language": bmad_language(args.repo),
        "sprint_status": os.path.abspath(path),
        "warnings": warnings,
        "error": flag_error,
    }

    waits = load_waits(args.repo)
    no_spec = specless_reviews(entries, args.repo)
    target, scope_error = (None, None) if flag_error else parse_scope(scope, entries, waits, no_spec)
    if scope_error and not result["error"]:
        result["error"] = scope_error
    if result["error"]:
        print(result["error"], file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
        return 2

    result.update(target)
    if target["mode"] == "story":
        result["parallel"] = "off"
    epic = target["epic"]
    result["epic_status"] = dict(entries).get(f"epic-{epic}")
    result["questions_file"] = questions_file(epic)
    epic_titles, story_text, epics_warning = load_epics(args.repo)
    if epics_warning:
        result["warnings"].append(epics_warning)
    result["warnings"].extend(load_heading_warnings(args.repo))
    result["epic_title"] = epic_titles.get(epic)
    if target["mode"] == "epic":
        result["stories"] = collect(entries, epic, story_text=story_text)
        if not result["stories"]:
            known = any(k.startswith(f"epic-{epic}") or
                        ((ks := key_story(k)) and ks[0] == epic)
                        for k, _ in entries)
            result["error"] = (f"epic {epic} has no unfinished stories"
                               if known else f"epic {epic} is not in sprint-status")
    else:
        result["stories"] = collect(entries, epic, target["story"], story_text)
        if not result["stories"]:
            key, _ = story_entry(entries, epic, target["story"])
            result["error"] = (f"story {epic}-{target['story']} is already done"
                               if key else f"story {epic}-{target['story']} is not in sprint-status")
    if not result["error"]:
        skip_specless(result, no_spec)
        if not result["stories"]:
            result["error"] = "no story to run: " + "; ".join(
                skip_review_note(s["id"]) for s in result["skipped"])
    if not result["error"]:
        check_waits(result, waits.get(epic, []), dict(entries), epic, own=target["mode"] == "story")
        result["stories"] = review_first(result["stories"])
    result["count"] = len(result["stories"])
    if result["error"]:
        print(result["error"], file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
