# CLI reference

[Русский](../ru/cli.md) · [Back to README](../../README.md)

`auto-bmad <command> [args]` runs `scripts/<script>.py` of the plugin with `python3`
(standard library only). While the plugin is enabled, its `bin/` is on the PATH of Claude
Code's Bash tool. Outside Claude Code, call `bin/auto-bmad` by its full path.

Most commands are called by the run itself; you need them for setup, statistics,
diagnostics and cleanup. Every command takes `--repo <dir>` (default: current directory)
and `--help`.

Common contract:

- JSON on stdout; the reason of a failure is in `error` (for `preflight` — the `blocking`
  list) and also on stderr;
- exit codes: `0` — done, `1` — call error (no such folder, missing argument), `2` — "not
  done by rule" (empty queue, ambiguous argument, file written by a person, blocking
  preflight finding);
- `ext fire` and `ext answer` always exit with `0`; hook results are in the fields;
- commits are made by the skill. Two exceptions: `story-finish` commits the tracking, the
  questions file and hook files, and `verify fix-spec --commit-story` commits the spec.

| Command | Script |
|---|---|
| `setup` | `setup.py` |
| `plan` | `plan_run.py` |
| `preflight` | `preflight.py` |
| `profile` | `write_profile.py` |
| `spec` | `read_spec.py` |
| `sync` | `sync_sprint.py` |
| `questions` | `open_questions.py` |
| `verify` | `verify.py` |
| `window` | `window.py` |
| `worktree` | `worktree.py` |
| `ext` | `ext.py` |
| `stats` | `stats.py` |
| `story-finish` | `story_finish.py` |

## setup

Project state by stages and writing of settings. Asks nothing; without `--write` writes nothing.
See [Install](install.md#set-up-a-project).

```bash
auto-bmad setup check [--repo .]
auto-bmad setup init [--repo .] [--level normal] [--parallel conservative] [--width 3] \
    [--android-module <m>] [--no-android] [--test-command CMD] [--write] [--force]
auto-bmad setup headless [--repo .] [--write] [--force]
auto-bmad setup allow [--repo .]
```

`check` — stages `env`, `bmad`, `plan`, `project`, `extras`, `headless` and `next`.
`init` — `.auto-bmad.toml` from what it finds. `headless` — the permissions file for
`claude -p` and a ready command. Code 2 — the file exists (without `--force`). `allow` — the
`allow` rules a run in auto mode needs for this project, the ones your Claude Code settings
do not cover yet (`missing`), the ones auto mode ignores, conflicts with `deny` and `ask`,
and text for `autoMode.allow`; it writes nothing. See
[Unattended runs](unattended.md#auto-mode-the-allow-rules).

## plan

Parses the run argument and builds the story queue from `sprint-status.yaml` (numeric
comparison, so `1-*` does not match `11-*`; retrospectives skipped; "Waits" lines checked).
Headings of the epics file are read with the grammar of BMad's own parser
(`bmad-sprint-planning/scripts/sprint_plan.py`): `## Epic <N>: <title>` and
`### Story <N>.<M>: <title>`, where `<M>` may carry a split letter (`### Story 2.6a: …`). The keywords are English, the title may be in any language.
A numbered heading outside this grammar (`## Épica 2: …`) is not read and goes to `warnings`.

```bash
auto-bmad plan --arg "epic-1 --deep" [--repo .]
auto-bmad plan --arg "1-3"
auto-bmad plan --arg ""          # default story
```

Returns `level`, `parallel`, `parallel_width`, `mode` (`epic` / `story`), `epic`,
`epic_title`, `story`, `stories` (each with `id`, `num`, `title` and `goal`), `count`, `warnings`, sometimes
`note` and `waiting`. Also `language` — the run language from BMad's `communication_language`
(`null` when it is not set) — and `questions_file` — the epic's open questions file,
relative to the repository (`_bmad-output/implementation-artifacts/epic-<N>-open-questions.md`).
Story numbers (`story`, `num`) are strings as in BMad's sprint-status keys: `"3"`, or `"6a"` for a
split story (key `2-6a-<slug>`, heading `### Story 2.6a: …`); they sort as 6, 6a, 6b, 7. Code 2 — ambiguous argument
or an unmet dependency.

## preflight

All checks before a story in one call.

```bash
auto-bmad preflight [--repo .] [--parallel] [--level normal]
```

Blocking (code 2): not a git repository; dirty working tree; missing
`.claude/skills/bmad-build-auto/SKILL.md`, `_bmad/scripts/render_skill.py` or
`_bmad-output/implementation-artifacts/sprint-status.yaml`; missing `_bmad/custom/`;
no `uv` on PATH; missing agent type `auto-bmad:bmad-story-runner`. Also returns `branch`,
`dirty_files`, `test_command`, `warnings`.

Checks after a story with a `preflight` command run it too (with `--level` — only the checks of
that level; `fast` — none). Its exit 2 is a blocking line `check <name>: …`, exit 1 a warning.
The `mockmatch` check uses it when `design_project` is set: Claude Design is not logged in and
there is no saved copy (`design`) — blocking; there is a copy — a warning that it may be stale.
With `design_artifact` and no saved copy — blocking: `claude -p` cannot read artifacts.

With `--parallel`: whether the engine files are tracked by git (`engine_untracked` with the
ignore rule and the fix), `parallel_ready`, leftover worktrees (`stale_worktrees`),
`has_origin`, `worktree_base_ref`, and `git_excluded` for `.claude/worktrees/`.

## profile

Writes the level profile `_bmad/custom/bmad-build-auto.user.toml` and excludes it from git
locally. See [Levels](levels.md#the-level-profile).

```bash
auto-bmad profile --level normal [--repo .] [--force]
```

Code 2 — the file was written by a person (no auto-bmad marker); `--force` overwrites it.
Code 1 — no `_bmad/custom/`.

## spec

Finds the spec of a story and reads its front matter; tells the run whether to start,
resume or only sync.

```bash
auto-bmad spec --story 1-3 [--repo .]
auto-bmad spec --slug issue-12 [--repo .]   # a task outside the epics: spec-issue-12-*.md
auto-bmad spec --story 1-3 --result [--repo .]
```

`--result` also returns `auto_run_result` (the last `## Auto Run Result` section), `commit`
(the last commit since `baseline_revision` that changed code outside `_bmad-output/`) and
`files` (the number of files in that commit), so the story runner does not read the spec for
its report. A value that cannot be found is `null`.

`route`: `resume`, `sync-only` or `ask-human`. Code 2 — zero or more than one spec.

## sync

Updates `sprint-status.yaml`: stories to `done`, the epic follows (`backlog` → `in-progress`,
all stories done → `done`), `last_updated` in the file's own format. Comments and order are kept.

```bash
auto-bmad sync --story 1-3 [--story 1-5] [--status done] [--repo .] [--dry-run]
```

Code 2 — nothing to change.

## questions

Writes a story's section in the epic's open questions file `epic-<N>-open-questions.md`.
The items come on stdin.

```bash
auto-bmad questions --story 1-3 --title "CSV import" \
    --spec _bmad-output/implementation-artifacts/spec-1-3-csv-import.md \
    --commit a1b2c3d [--status done|blocked] [--repo .] < items.md
auto-bmad questions ... --items-file items.md     # the same, the items from a file
auto-bmad questions --story 1-3 --none --repo .   # no questions: remove the section
```

Returns `path` (absolute) and `questions_file` (relative to the repository). Code 2 — the
file was written by a person, or there was nothing to remove.

## verify

Checks after a story. See [Checks](checks.md).

```bash
auto-bmad verify plan --story 1-3 --base <sha> --commit <sha> --level normal [--title T] [--repo .]
auto-bmad verify baseline [--repo .]
auto-bmad verify run --name project-tests [--repo .]
auto-bmad verify attempt --story 1-3 --level normal [--repo .]
auto-bmad verify fix-spec --spec <path> --pass N [--repo .] < problems.md
auto-bmad verify fix-spec --spec <path> --pass N --problems-file F --commit-story 1-3 [--repo .]
```

`plan` — which checks apply to the story diff (`verifiers`, `skipped`, `fix_limit`).
`baseline` — runs the project tests once and stores the result. `run` — runs a
`kind = "command"` check and returns `verdict`. `attempt` — counts a fix and says whether
one more is allowed (`fix_allowed`). `fix-spec` — adds fix tasks to a `done` spec and moves
it to `in-progress`; `--problems-file` reads the problems from a file, `--commit-story` also
commits the spec. Code 2 — no checks, limit reached, or the spec is not `done`.

## window

Says whether the next story (or wave) fits into the time window and the usage limits.
See [Unattended runs](unattended.md#time-window-and-usage-limits).

```bash
auto-bmad window [--stage next-story|next-wave] [--deadline <epoch>] [--reserve-min N] \
    [--limits-file <path>] [--stop-at-five-hour-pct N] [--stop-at-seven-day-pct N]
```

Arguments win over environment variables. Returns `take_next` and `reason`. Code 2 — do
not take the next one. No window and no limits — always code 0.

## worktree

Lists and removes worktrees of parallel stories; restores interrupted work.

```bash
auto-bmad worktree list [--repo .]
auto-bmad worktree prune [--repo .]                    # remove worktrees whose branches are merged into HEAD
auto-bmad worktree remove --path <path> [--repo .] [--force]
auto-bmad worktree remove --path <path> --keep-branch  # free the branch for a resumed run
auto-bmad worktree remove 1-3 [--repo .] [--force]     # a worktree created by "add"
auto-bmad worktree add 1-3 [--repo .]                  # to restore an interrupted story
auto-bmad worktree seed --from <main tree> [--repo .]  # copy local BMad settings into a worktree
```

`list` shows worktrees under `.claude/worktrees/` or on `auto-bmad/*` branches. Each one
has its last three commits (`log`) and uncommitted files (`dirty`); `dirty: null` with
`error` — the state is unknown, `missing: true` — the directory is gone. The main tree is
never listed. `--force` also discards uncommitted work.

## ext

Config layers, events and hooks. See [Configuration](config.md) and [Hooks](hooks.md).

```bash
auto-bmad ext config [--repo .]
auto-bmad ext fire <event> [--story 1-3] [--title T] [--epic N] [--level L] [--spec P] \
    [--commit SHA] [--status S] [--questions-file P] [--data JSON] [--repo .]
auto-bmad ext answer --hook <name> --option <id> [--repo .]
```

`config` — the merged config, its `sources` and `warnings`. `fire` — calls the hooks of an
event and writes the events journal. `answer` — passes a person's choice to one hook.

## stats

Run statistics. See [Statistics](stats.md).

```bash
auto-bmad stats show [--epic N] [--last N] [--json] [--repo .]
auto-bmad stats record --session <id> [--repo .]
auto-bmad stats backfill [--repo .]
```

## story-finish

The finishing steps of a story or a wave in one call. The run uses it instead of a chain of
commands: without a person, Claude Code's auto mode checks a long chain as a whole and may
deny it, and then every part is lost.

```bash
auto-bmad story-finish --input <file.json> [--session <id>] [--repo .]
```

The input is a JSON file:

```json
{
  "epic": 1, "level": "normal",
  "stories": [
    {"story": "1-3", "title": "CSV import", "spec": "<path>", "commit": "<sha>",
     "status": "done", "questions": "<Needs attention items, or empty>",
     "verify": {"status": "pass", "fixes": 0, "checks": {"project-tests": "pass"}}}
  ],
  "wave": 2,
  "run_end": {"status": "done", "done": 3, "left": 0}
}
```

Every key is optional; `epic` is needed only when `stories` is empty. The order of the steps:

1. `verify-done` for each story with `verify`;
2. `sync` of the `done` stories;
3. `questions` for each story: a section from `questions`, or no section when it is empty;
   a `blocked` story needs the blocker text;
4. one commit of `sprint-status.yaml` and the questions file;
5. `story-done` / `story-blocked` per story, then `wave-merged` when `wave` is set;
6. `run-end` when `run_end` is set;
7. `stats record` when `--session` is given.

Files a hook returns in `files` are committed right after its event, with its message. A failed
step does not stop the others. The response: `ok`, `commit` (the tracking commit or `null`),
`steps` (each with `ok` and `detail`), `messages` and `links` from hooks, `warnings`, `failed`.
Code 2 — some step failed (see `failed`); a hook error is only a warning.

