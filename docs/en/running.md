# Running

[Русский](../ru/running.md) · [Back to README](../../README.md)

> **Language.** The run talks to you in the **run language**: progress lines, reports and
> the items of the open-questions file. The run language is BMad's `communication_language`
> in the order BMad itself reads it: `_bmad/custom/config.user.toml`, `_bmad/custom/config.toml`,
> `_bmad/config.user.toml`, `_bmad/config.toml`, then older BMad config files. If it is
> not set, the run uses the language you write in; an unattended run with no language set
> uses English. Commit messages, machine markers (`WORK_START`, `STORY_DONE`…) and
> the script scaffolding of the open-questions file are always English. The examples below
> are in English.

## Arguments

```
/auto-bmad:auto-bmad [story-id | epic-N | nothing] [--fast | --normal | --deep]
                     [--parallel-fast [N]] [--width N] [--no-parallel]
```

| Argument | What runs |
|---|---|
| `epic-1` (also `epic 1`, or the word "epic" in another language) | every story of epic 1 that is not `done`: stories in `review` first, then the rest in number order; retrospective entries are skipped. "Waits" cuts the queue in number order, and a `review` story waits for nothing; a `review` story without a spec, or one with other work committed after it, is skipped with a line in the report |
| `1-3` (also `1.3`, `story 1-3`; a BMad split story: `2-6a`) | one story |
| nothing | the default story: the first `in-progress` story, otherwise the first `review` story the run can take (see below), otherwise the first `ready-for-dev`, otherwise the first `backlog` story of an `in-progress` epic, otherwise the first `backlog` story at all |

A pair `N-M` or `N.M` means a story; the story number may have a split letter (`2-6a`). One word and one number (`epic-7`, `epic 7`, the same
word in another language) or a bare number means an epic. Anything else, for example
`story 7` or `fix bug 12`, is not guessed: the run asks you what you meant.

| Flag | Effect |
|---|---|
| `--fast`, `--normal`, `--deep` | review depth for this run; see [Levels](levels.md). Two different levels in one call is an error |
| `--no-parallel` | stories of an epic run one at a time |
| `--parallel-fast [N]` | aggressive grouping of stories into waves; an optional number sets the wave size |
| `--width N` | wave size (default 3) |

Flags override the `[run]` section of your config (see [Configuration](config.md#run)).
Without flags and config, the level is `normal` and parallel mode is `conservative`
with width 3. The old `--parallel` flag was removed: the run warns and, if a number
follows it, takes it as the width.

Examples:

```
/auto-bmad:auto-bmad epic-1
/auto-bmad:auto-bmad epic-2 --deep --no-parallel
/auto-bmad:auto-bmad epic-3 --fast --width 4
/auto-bmad:auto-bmad 1-3
/auto-bmad:auto-bmad
```

## Epic dependencies

An epic in the epics file can declare what it waits for, with a line under its heading:

```markdown
## Epic 3: Reports

**Waits:** epic 2
```

`Waits for:` and `Depends on:` work too. Write the line in English in a project of any language:
the words `epic`, `story` and `and` are what the script reads. Before a run, auto-bmad compares the line with `sprint-status.yaml`:

- the whole epic waits for something not `done` — the run does not start and says what
  it waits for;
- a condition for some stories only (`**Waits:** 3.4–3.6 — epic 2`) — the queue
  stops before the first waiting story, and the reason goes to the final report. A range
  includes the split stories inside it: `3.4–3.6` covers `3.5a`; `3.5a–3.5c` covers
  `3.5a`, `3.5b`, `3.5c`. A split story can also be named alone: `story 2.6a`;
- a condition in free words that the script cannot check counts as not met.

## What happens per story

Before the first story, the run:

1. Parses the argument and builds the queue from `sprint-status.yaml`; titles and goals
   come from the epics file. Its headings follow BMad's format, `## Epic <N>: <title>` and
   `### Story <N>.<M>: <title>` (a split story: `### Story 2.6a: …`): English keywords, a title in any language. BMad's sprint
   planning reads the same headings (see [CLI](cli.md#plan)).
2. Fires the `run-start` hook event.
3. Runs **preflight** (see [CLI](cli.md#preflight)): a clean working tree, the BMad engine,
   `sprint-status.yaml`, `_bmad/custom/`, `uv`, the plugin's agent types. Anything missing
   stops the run. A dirty tree is shown to you; the run does not commit or revert your work.
4. Writes the **level profile** to `_bmad/custom/bmad-build-auto.user.toml` (excluded from
   git locally, through `.git/info/exclude`). If that file exists and was written by a
   person, the run stops instead of overwriting it.
5. Runs the project tests once as a **baseline** (not on `fast`).
6. Prints the level and a table of the stories it will run.

Then, for each story, you see a progress line:

```
[Story 2/5] ✅ Preflight → ⏳ Story run → ⬚ Check → ⬚ Sprint sync → ⬚ Report
```

The step labels are in the run language; the symbols ✅ ⏳ ⬚ and the arrows are fixed.

| Step | What happens |
|---|---|
| 1. Preflight | Repeated before every story. Then the `story-start` hook event |
| 2. Story run | A fresh `auto-bmad:bmad-story-runner` subagent runs BMad's `bmad-build-auto` engine: spec → code → review layers → triage and fixes → verification from the spec → commit. Extra review passes up to the level's limit. Only a short report comes back, so context does not pile up across stories |
| 3. Result | `done` or `blocked` |
| 3.5. Checks | On `normal` and `deep`: project tests and other checks from the config; a problem is fixed by the engine and checked again. See [Checks](checks.md) |
| 4. Sprint sync | The story becomes `done` in `sprint-status.yaml`, the epic status follows; the story's open questions go to the epic's file. One commit. Then the `story-done` hook event |
| 5. Report | The story report and its run statistics |
| 6. Next | Takes the next story without asking — unless a time window says stop (see [Unattended runs](unattended.md#time-window-and-usage-limits)) |

A `blocked` story stops an epic run: its notes go to the open-questions file (committed),
the `story-blocked` hook event fires, and the report lists what is left.

Every story report ends with a machine line for external runners:
`STORY_DONE: <id> commit=<sha> files=<n>`, or `STORY_BLOCKED: <id>` for a blocked story
(see [Integration examples](examples.md#markers-in-the-output)).

The run never pushes. Commits made during a run:

- the engine's commit with the story code;
- fix commits after a failed check (a spec update, then the engine's fix);
- a commit with the test flow a check left behind (for example an adbm Maestro flow);
- the sprint-tracking commit (with the open-questions file);
- in parallel mode, merge commits.

## Reports

Each story report has three parts, written for a reader who knows neither the code nor BMad:

- **What was done** — in plain words, from the user's point of view;
- **How to check** — numbered steps: what to run, open, tap, and what you should see;
- **Needs attention** — only decisions for a human. Each item has the same form:
  what is wrong → what it threatens → 2–3 options with their cost → a recommendation.

At the end of an epic you get the epic report: what the program can do now, a line per
story with its commit, a shared "how to check" scenario, all "needs attention" items
merged and sorted, three lines of run statistics, and next steps (`bmad-retrospective`,
`auto-bmad stats show`, `bmad-walkthrough`).

## Open questions file

"Needs attention" items do not stay only in the chat. After every story they are written
to one file per epic:

```
_bmad-output/implementation-artifacts/epic-<N>-open-questions.md
```

One section per story, with a link to its spec and the commit. A blocked story gets
a section too, marked `(blocked)`. The file is committed with the sprint tracking.

The script owns the file. Each story section sits between anchors:

```markdown
<!-- story:1-3 -->
## Story 1-3 — CSV import
...
<!-- /story:1-3 -->
```

A split story has its own section with the letter: `<!-- story:2-6a -->`. A repeated run of the same story replaces only its section. Notes you write outside the
anchors are kept. If a file with that name exists and was not created by auto-bmad,
it is left alone.

## Resuming an interrupted story

Run the same command again. Before starting a story, auto-bmad looks for its spec:

| Spec status | What the run does |
|---|---|
| no spec | starts the story from scratch |
| `draft`, `ready-for-dev`, `in-progress`, `in-review` | passes the spec path to the engine, which continues from that step without redoing finished work. You see a line such as "Story 3-7: continuing interrupted work (spec in-review)" |
| `done`, the story is `review` in `sprint-status.yaml` | the code is committed and waits for review: passes the spec path to the engine, which runs a fresh review pass, fixes what it finds and commits. You see a line such as "Story 5-1: reviewing committed code (status review in sprint tracking)" |
| `done`, the story is `review`, other work committed after it | the engine reviews everything since the spec's baseline, so it would review that work too: the story is skipped with a line in the report and an item in "Needs attention" — review it by hand or move it to another status |
| `done`, any other sprint status | the work is done, only tracking lagged: syncs `sprint-status.yaml` without running the engine |
| no spec, the story is `review` in `sprint-status.yaml` | the code was written outside the engine, and there is no spec to review it against: an epic run and a run without an argument skip it with a line in the report; named on its own, it is shown to you and the run stops |
| `blocked` or unknown | shows it to you and stops |
| two or more specs for one story | shows the list and asks which one is real |

## Parallel waves

In epic mode, parallel waves are the default. The run splits the queue into **waves**:
stories inside a wave run at the same time, each in its own git worktree under
`.claude/worktrees/` and on its own branch `auto-bmad/<story-id>`; waves run one after
another. Story order is kept: a wave is always a continuous slice from the start of the queue.

| Mode | Which stories share a wave |
|---|---|
| conservative (default) | only stories with no sign of overlap: no stated dependency, no shared file or module, no "creates / uses" link, no shared build point (config, router, DI, migrations, DB schema), no unclear scope |
| aggressive (`--parallel-fast`) | everything except stated dependencies and shared build points; file overlap is resolved at merge time |

The wave size is at most `N` (default 3). Before the first wave you get a table of waves
with the reason a story was moved to a later wave.

After a wave, the orchestrator:

1. Merges the branches one by one, in queue order (`git merge --no-ff`). It resolves
   conflicts itself with minimal changes and reports each resolution under
   "needs attention". If it is not sure, it aborts that merge and asks you; the other
   stories of the wave are still merged.
2. Removes merged worktrees and branches, then runs the project tests on the merged
   result. Tests that fail after a green baseline stop the epic; the run does not fix them
   and does not revert merges without your word.
3. Runs the other checks (device, custom) for each merged story, one at a time.
4. Syncs `sprint-status.yaml` and the open-questions file in one commit per wave, then
   fires `story-done` / `story-blocked` per story and `wave-merged` once.

A blocked story does not cancel the merge of the others. Its branch and worktree stay,
and the epic stops after that wave.

### When it falls back to sequential

- `--no-parallel`, or `parallel = "off"` in `[run]`;
- a single-story run, or one story left in the queue (a one-story wave runs as a normal
  sequential story);
- the engine files (`.claude/skills/bmad-build-auto/SKILL.md`, `_bmad/scripts/render_skill.py`)
  are not committed to git, so a new worktree would not have them. Preflight names the
  cause (an ignore rule or an uncommitted file) and the fix; the run goes on sequentially
  and repeats the fix in the final report;
- a story subagent reports that it did not get its own worktree — the rest of the wave
  runs sequentially.

If the repository has no `origin` and Claude Code's `worktree.baseRef` setting is `fresh`
(the default), creating worktrees may fail. Preflight warns about it; set
`worktree.baseRef` to `head` with `/config`.

If your tests walk the file system (looking for duplicates, TODOs and similar), they will
see the copies of the code in `.claude/worktrees/`. Preflight warns when no test config
mentions `.claude`; exclude that folder in your test configuration.

### An interrupted parallel run

Work of an interrupted wave lives in the `auto-bmad/<story-id>` branches, not in the main
tree. Preflight reports leftover worktrees, and the run goes through them with you, one by
one: a finished story is merged; an unfinished one can be continued from its branch or
restarted; an empty one is removed. Nothing with commits is deleted without your word.

Manual cleanup:

```bash
auto-bmad worktree list --repo .
auto-bmad worktree remove --path <path> --repo .
```

`--force` also discards uncommitted work in that worktree.

## Progress in the Claude Code UI

The run keeps a task list: one task per story plus the final report (epic mode), or one
task per step (story mode). If the session has no task tools, progress is shown as text
only; the run tells you that the list can be turned on with the variable
`CLAUDE_CODE_ENABLE_TODO_TOOLS=1` in `~/.claude/settings.json`.
