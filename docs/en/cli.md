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
  preflight finding), `3` — the tests still run in the background (`test`, `verify baseline`,
  `verify run`): call the same command again;
- `ext fire` and `ext answer` always exit with `0`; hook results are in the fields;
- commits are made by the skill. Two exceptions: `story-finish` commits the tracking, the
  questions file and hook files, and `verify fix-spec --commit-story` commits the spec.

| Command | Script |
|---|---|
| `setup` | `setup.py` |
| `plan` | `plan_run.py` |
| `preflight` | `preflight.py` |
| `profile` | `write_profile.py` |
| `roles` | `roles.py` |
| `spec` | `read_spec.py` |
| `sync` | `sync_sprint.py` |
| `questions` | `open_questions.py` |
| `verify` | `verify.py` |
| `window` | `window.py` |
| `worktree` | `worktree.py` |
| `ext` | `ext.py` |
| `stats` | `stats.py` |
| `story-finish` | `story_finish.py` |
| `evidence` | `evidence.py` |
| `land` | `land.py` |
| `agent-config` | `agent_config.py` |
| `doctor` | `doctor.py` |
| `run` | `run_queue.py` (`--manifest`: `run_story.py`) |
| `engine` | `engine.py` |
| `agent-smoke` | `agent_smoke.py` |
| `stub` | `stub.py` |
| `test` | `testrun.py` |

## setup

Project state by stages and writing of settings. Asks nothing; without `--write` writes nothing.
See [Install](install.md#set-up-a-project).

```bash
auto-bmad setup check [--repo .]
auto-bmad setup agent --agent codex [--model MODEL] [--effort high] [--review-model MODEL] \
    [--review-effort E] [--executable PATH] [--env JAVA_HOME] [--timeout 3600] \
    [--disable-agent-checks] [--layer project|local] [--add|--select] [--compact|--advanced] [--level fast|normal|deep] [--repo .] [--write]
auto-bmad setup agent --agent claude [--layer project|local] [--add|--select] [--repo .] [--write]
auto-bmad setup init [--repo .] [--level normal] [--parallel conservative] [--width 3] \
    [--android-module <m>] [--no-android] [--test-command CMD] [--write] [--force]
auto-bmad setup headless [--repo .] [--write] [--force]
auto-bmad setup allow [--repo .]
auto-bmad setup role --role <role> [--model M] [--effort E] [--layer project|user|local] [--repo .] [--write]
auto-bmad setup local [--repo .] [--write]
```

`check` — stages `env`, `bmad`, `plan`, `project`, `execution`, `extras`, `headless` and `next`.
It lists executor choices in `agents`. CLI `execution` checks profiles and the engine contract,
without inference, tests or hooks; interface compatibility alone is not a live model test.
`init` — `.auto-bmad.toml` from what it finds. `headless` — the permissions file for
`claude -p` and a ready command. Code 2 — the file exists (without `--force`). `allow` — the
`allow` rules a run in auto mode needs for this project, the ones your Claude Code settings
do not cover yet (`missing`), the ones auto mode ignores, conflicts with `deny` and `ask`,
and text for `autoMode.allow`; it writes nothing. See
[Unattended runs](unattended.md#auto-mode-the-allow-rules). `role` — the
[`[roles.<role>]`](config.md#roles) table in `.auto-bmad.toml` or, with `--layer user`, in the
personal config. `--layer local` writes machine-only overrides to the ignored `.auto-bmad.local.toml`,
with an exact backup of existing content and refusal to overwrite a tracked local file.
Without `--model` and `--effort` it removes the table of that layer; `default`
as a value clears an override of a lower layer. Without `--write` it only shows the text.
`local` — whether [`.auto-bmad.local.toml`](config.md#four-layers) is out of git (`exists`,
`tracked`, `ignored`, `in_gitignore`, `fix`). Closed means a rule in the project's
`.gitignore`: a rule only in `.git/info/exclude` or your global ignore file holds on this
machine alone. `--write` adds the line to `.gitignore` when it is not there. `check` shows the same in
`project.local`.
Code 1 — a bad value, or the role is written in a form the command does not edit (a `[roles]`
table, an inline table): set it by hand.

**Executor setup.** `$auto-bmad-setup` collects these choices in Codex; `/auto-bmad:setup` does so
in Claude Code. `agent` previews a safe update of existing settings, or creates agent settings if
the selected layer is absent. `init --agent codex` (optional `--model MODEL`) creates a
new full project config using the usual init flags. Native Claude is `--agent claude`; omitting
`--agent` on `init` keeps its old behavior. Kimi and Claude CLI are listed as unavailable.

One `.auto-bmad.toml` stores shared project defaults: native Claude models in `[roles.*]`,
compact Codex models in `[executors.codex]` (older `[agents.*]`/`[routing.*]` are supported), plus common tests/hooks/run settings.
Commit this file with the project. Machine-specific additions and model overrides go in the ignored
`.auto-bmad.local.toml` (`--layer local`); this last layer wins without copying the whole config.
Setup refuses to treat an already tracked local file as private.

Known skill frontends select the current chat's executor for each invocation: Codex uses Codex,
Claude Code uses native Claude. They never rewrite the stored default just to run.
`agent --agent codex --add --model MODEL --write` adds Codex settings while preserving
`[execution].backend`; omit profile options to reuse saved models/efforts/timeouts/environment
(`profiles_reused=true`). The Codex setup helper supplies `--agent codex --add` automatically
for `agent`; a new `init` chooses its initial default. `--layer local --add` stores personal additions only.

Outside a known frontend, use `auto-bmad --executor codex ...` (or `claude`) for an invocation;
`AUTO_BMAD_EXECUTOR` carries that choice to nested processes. With no context, the stored backend
remains the fallback. `setup agent --agent codex --select --write` explicitly changes that default;
the standalone `agent` command keeps this historical selection behavior without `--add`.
New Codex settings use built-in models when options are omitted; existing advanced profiles are reused.
`--level fast|normal|deep` edits one compact level, while common settings apply to every level.
`--compact` migrates existing Codex routes with a backup; `--advanced` writes explicit profiles.
See [compact settings and precedence](config.md#compact-codex-models).

Compact Codex defaults are `gpt-6.1-sol/high` for work and `gpt-6-astra/high` for read-only review.
The common model block covers all levels without duplicated routes. Native role values are retained.
Advanced generation retains its historical review-defaults-to-write behavior.
Agent-based checks (mockmatch, adbm and custom verifiers) are retained and run through the configured
`verifier` role. `--disable-agent-checks` is an optional explicit opt-out; settings remain in TOML
with `enabled=false`. Switching executors never automatically re-enables previously disabled checks.
Command checks, hooks and run settings remain. Models are exact CLI IDs, not Claude aliases.

Before `--write`, all config layers are validated. Higher local overrides cause an error instead
of silently choosing another model; `agent --layer local` configures only this machine. No personal
config is rewritten. Writes are atomic under the source lease, preserve unrelated TOML values and
make a private exact backup under `.auto-bmad/setup-backups/` when an existing file changes.
An identical selection makes no new backup. `init --agent` refuses an existing file even with
`--force`: migrate with `agent`. `setup role` remains native-only. For CLI projects `headless`
returns the shared run command and writes no Claude permission settings. No setup action starts a run.
Explicit native selection masks CLI routes inherited from lower layers without modifying those
layers; native model/effort settings apply and a warning explains inactive routes. CLI settings
without an explicit backend still fail closed.

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
auto-bmad plan --arg "epic-1 --worktree"
```

Returns `level`, `parallel`, `parallel_width`, `mode` (`epic` / `story`), `epic`,
`epic_title`, `story`, `stories` (each with `id`, `num`, `title` and `goal`), `count`, `warnings`, sometimes
`note` and `waiting`. `worktree` — whether the run goes in its own worktree (`--worktree`,
`--no-worktree`, `[run] worktree`); when it is `true`, also `worktree_name` (`epic-1`, `1-3`),
`worktree_branch` (`bmad/epic-1`) and `worktree_arg` — the argument for the second `plan` call
inside the worktree. Also `language` — the run language from BMad's `communication_language`
(`null` when it is not set) — and `questions_file` — the epic's open questions file,
relative to the repository (`_bmad-output/implementation-artifacts/epic-<N>-open-questions.md`).
Story numbers (`story`, `num`) are strings as in BMad's sprint-status keys: `"3"`, or `"6a"` for a
split story (key `2-6a-<slug>`, heading `### Story 2.6a: …`); they sort as 6, 6a, 6b, 7. Code 2 — ambiguous argument
or an unmet dependency.

Stories in `review` (code written, waiting for review) go to the head of `stories`. "Waits"
is checked in number order first, and a `review` story waits for nothing: it stays in the queue
even behind a cut. A `review` story without a spec, or with other work committed after it (`later_commits` of
`spec`), is not in the queue: it is in `skipped` (`id`, `title`, `reason`) and in `note`. The
default pick passes it too, and lists it in `skipped` and `note` when it went past it. Named on its own
(`--arg "5-1"`) it is code 2.

## preflight

All checks before a story in one call.

```bash
auto-bmad preflight [--repo .] [--parallel] [--level normal]
```

Blocking (code 2): not a git repository; dirty working tree; missing
`.claude/skills/bmad-build-auto/SKILL.md`, `_bmad/scripts/render_skill.py` or
`_bmad-output/implementation-artifacts/sprint-status.yaml`; missing `_bmad/custom/`;
no `uv` on PATH; missing agent type `auto-bmad:bmad-story-runner`; an invalid
[`[roles.*]`](config.md#roles) value (`model` or `effort` outside the list, a `provider` other
than `anthropic`). Also returns `branch`,
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
locally. See [Under the hood](engine.md).

```bash
auto-bmad profile --level normal [--repo .] [--force]
```

Code 2 — the file was written by a person (no auto-bmad marker); `--force` overwrites it.
Code 1 — no `_bmad/custom/`, or the `[roles]` config has errors.

`agent_args` in the output — the `model` / `effort` overrides from
[`[roles.*]`](config.md#roles), by role. The profile already carries them for the engine's
subagents; the skill passes them itself for `story-runner` and `verifier`.
`triage_subagent` — whether `[run] triage_subagent` turned on fact I
([Under the hood](engine.md#the-facts)). `test_command` — the test command of fact J; `null` —
there is none, and the profile has no fact J.

## roles

Model and effort of every role after the config layers merge: the agent type default,
the override and what the run will use.

```bash
auto-bmad roles [--repo .]
```

`roles.<role>.args` — the parameters that go into the `Agent` call, `{}` when there is no
override. Code 2 — the config has errors (`errors`); preflight blocks the run on the same errors.

## spec

Finds the spec of a story and reads its front matter; tells the run whether to start,
resume or only sync.

```bash
auto-bmad spec --story 1-3 [--repo .]
auto-bmad spec --slug issue-12 [--repo .]   # a task outside the epics: spec-issue-12-*.md
auto-bmad spec --story 1-3 --result [--repo .]
```

`--result` also returns `auto_run_result` (the last `## Auto Run Result` section), `commit`
(the story's engine commit: the last commit since `baseline_revision` that changed both the spec
and code outside `_bmad-output/`, so a later story's commit is not taken; a spec never committed
with code — the last commit that changed code) and
`files` (the number of files in that commit), so the story runner does not read the spec for
its report. A value that cannot be found is `null`.

`route`: `resume`, `review`, `skip`, `sync-only` or `ask-human`. Code 2 — zero or more than one spec.
With `--story` the answer also has `sprint_status` — the story's status in `sprint-status.yaml`.
A `done` spec of a story in `review` there gets `review`: the engine reviews the committed code
again; then the answer also has `commit` — the story's engine commit (the last one since the
baseline that changed both the spec and code; merge commits do not count) — and `later_commits`, the code commits of other
work after it (`null` — unknown: the spec was committed apart from the code). `later_commits`
above 0 gives the route `skip` with a `reason`: the engine would review that work too.
`later_commits` null keeps `review`. A `review` story without a spec gets code 2 with `route: ask-human`. `baseline` — the
spec's baseline revision (`baseline_revision`, or `baseline_commit` of older engine versions):
the story base for the checks after a `review` run.

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

`baseline` and `run` run the command through [`test`](#test): the folder's lock and the kept
result. Code 3 (`verdict: running`) — the tests still run in the background, repeat the same call.

## test

Runs the project tests under the folder's lock and keeps the result for the same code. Every
role of a run runs the tests through it: the engine (fact J), the implementer, `verify` and the waves.

```bash
auto-bmad test [--repo .]                                  # the project-tests check of the config
auto-bmad test --command 'scripts/check.sh backend' [--repo .]   # part of the suite
auto-bmad test --rerun [--repo .]                          # again, though the code has not changed
auto-bmad test --wait 60 [--repo .]                        # wait 60 s, not 540
auto-bmad test --name <check> --timeout 3600 [--repo .]    # another kind=command check; its own time limit
```

- **Lock.** One run at a time in a folder. A second one waits for the first, because the
  folder's test databases, ports and build are shared. Neighbouring folders (worktrees) do not wait:
  a project whose folders share test resources must isolate them itself (sample-project's `check.sh`
  gives each folder its own containers and ports).
- **Kept result.** The key is the content of the working copy with untracked files, plus the
  command. Edits under `_bmad-output/` and `.auto-bmad/` do not change it, and neither does a commit.
  The same key — the kept result comes back at once with `reused: true`, green or red.
  A timeout is not kept. A tree changed during testing returns `tree_changed: true` and is
  not cached; the resulting tree needs a fresh run. Ignore generated reports or place them
  under `.auto-bmad/`. `--rerun` is for a failure whose cause was outside the code: Docker
  was not running, say. It still takes a result under 120 s old — the answer to its own run;
  after `running` call again without `--rerun`. `verify baseline` runs again a red result
  older than 15 minutes: a failure kept from another day must not hide a story's breakage.
- **Long runs.** The command runs in its own process and outlives the Bash call. After
  `--wait` seconds (540 by default) the answer is `verdict: running`, code 3. The same call
  again waits for that same run instead of starting a new one, also when the run itself
  changed the tree (reports, snapshots). The time limit is `--timeout`, else the check's
  `timeout` (1800 s by default), with `--command` too.

Output: `verdict` (`pass`, `problem`, `running`), `code`, `seconds`, `reused`, `tail` — the end
of a failed output, `log` — the full output. State lives in the folder's `.auto-bmad/tests/`,
with `history.jsonl`: one line per call, with the run time and `reused`.

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
auto-bmad worktree start epic-1 [--repo .]             # the worktree of a whole run: create or resume
```

`start` — the worktree of a [run in its own worktree](running.md#run-in-its-own-worktree):
the branch `bmad/<name>` in `.claude/worktrees/bmad-<name>` of the main tree, from its HEAD.
A live worktree of the branch is resumed (`resumed: true`), a branch without a directory gets
one again. Returns `path`, `branch`, `created`, `resumed`, `base_branch`, `seeded` (copied
local files; only git-ignored ones are copied), `left_in_main` (local files not ignored,
left in the main tree — the config readers take the config layers from there), `main_dirty` (uncommitted files of the main tree, not in the run) and `land`
(the merge command). The worktree lies inside the project folder, closed from git in
`.git/info/exclude`. `list` and `prune` do not show run worktrees.

`list` shows worktrees under `.claude/worktrees/` or on `auto-bmad/*` branches. Each one
has its last three commits (`log`) and uncommitted files (`dirty`); `dirty: null` with
`error` — the state is unknown, `missing: true` — the directory is gone. The main tree is
never listed. `--force` also discards uncommitted work.

## land

Merges the branch of a [run in its own worktree](running.md#auto-bmad-land) into the
branch of the main tree. Works from the main tree or from inside the worktree.

```bash
auto-bmad land bmad/epic-1 [--repo .] [--no-tests] [--onto-current] [--cleanup]
```

Returns `merged`, `base`, `merge_commit`, `conflicts`, `sprint_merged` (the keys changed when
`sprint-status.yaml` was resolved), `tests` (`verdict`, `command`, `tail`), `removed_worktree`,
`removed_branch`, `warnings`; `dirty` — uncommitted files of the main tree on refusal. Code 2 —
uncommitted changes, the main tree on another branch than the run's base (`recorded_base`;
`--onto-current` merges anyway), a branch with no commits of its own (`--cleanup` removes it
anyway), a conflict in code (the files are in `conflicts` and on stderr), tests failed;
nothing is merged then. Code 1 — no such branch, the main tree is not on a branch,
git older than 2.38.

Tests run in a fresh temporary worktree. An existing `auto-bmad-land` directory is never reused
or removed. If tests change tracked, untracked or ignored files, the merge stops and
`tests.worktree` points to the kept tree. Test-runner files under `.auto-bmad/tests/` belong to
the runner and do not count as project output. Locked metadata or an unknown state also stops
the merge. Cleanup keeps a run worktree with unknown files and reports `warning_cleanup`.

## CLI backend: Codex and sequential epics

The CLI runtime requires POSIX macOS/Linux (`fcntl`, process groups and fork); Windows is not validated.
The shared CLI owns the queue; native `bmad-build-auto` owns each story lifecycle. Role profiles choose
adapter, executable, model, effort and permissions. Codex passed a live single-story smoke. Kimi/Claude CLI
adapters remain disabled until their contracts are validated; native Claude Code retains its separate legacy path.
See the [configuration schema and profiles](../multi-agent/CONFIG_EXTENSION.md).

```bash
auto-bmad agent-config --repo . --level normal
auto-bmad doctor --repo . --level normal
auto-bmad run plan --repo . --arg "epic-1"
auto-bmad run --repo . --arg "1-3" --allow-model
auto-bmad run --repo . --arg "epic-1 --normal" --allow-model --timeout 7200
```

`run` requires effective `execution.backend="cli"` and a clean source worktree.
The Codex skill or `auto-bmad --executor codex run ...` selects CLI without changing the stored default. It creates a unique linked worktree
and `codex/auto-bmad/...` branch from exact current HEAD, carries allowed local BMAD/CLI settings,
freezes configuration and prepares an engine snapshot. Epics run sequentially with a fresh controller per story.
Done stories are skipped, Waits/dependencies are respected, and a failed story stops the queue. The source branch
stays unchanged. Results contain `run_completed`, `stories`, `done`, `left`, `remaining`, `worktree`, `branch`,
`session`, hook results and `merge_policy="manual"`. Partial or stopped epics are not success.
Merge and push require a separate human command. Preserved worktrees are never deleted by the runtime.

Before each story, `window.py` checks the window, clean-stop and live file. It stops between stories.
`--timeout` is a separate total hard limit that may interrupt the active story. `--parallel-fast`, `--width`
and `--no-worktree` are explicitly refused; waves and automatic crash recovery are not implemented.
`run-start`, `story-start` and `run-end` fire configured hooks; story finishing retains existing events.
Hook files are committed in the run worktree, hook questions return to the human, and ext.py's unattended policy remains.
Host hooks/checks inherit operator environment; model-role processes keep their explicit environment allowlists.
Wrapper budgets account for configured hook timeouts, with the overall run deadline still enforced.
Changed configuration cannot introduce new hooks mid-run. Final hooks that change the verified code tree report needs_attention.

```bash
auto-bmad run status --session /returned/path/session.json
auto-bmad run cancel --session /returned/path/session.json
```

Sessions and results live in `<git-common-dir>/auto-bmad-sessions/<id>/`, outside the agent-writable worktree.
The broker transfers writer ownership to implementer/compiler/triager and accepts a parallel read-only review batch.
Each reviewer receives an authoritative exact-base diff including new/binary files and its original context restrictions.
Every role's `task_id` is the story ID; the broker assigns unique attempt IDs. The controller reads the native workflow,
keeping activation/on_complete, triage, fix and followup policies. Git commits and rollback go through the broker;
a backup patch precedes rollback and an intent gap blocks progress. Checkpoint tests and external command checks
run on the host under the folder lock, caching tree/command results in protected state. Writable `.auto-bmad/tests/`
cache cannot authorize completion. Tests inside roles use `auto-bmad test --session <session.json>`.
Commands must not escape through setsid/daemonization. Timeout, cancel and host death stop managed groups;
a cleanup sentinel retains inherited execution ownership until session test workers and this run/tree's stubs stop.
Unknown cleanup reports `needs_attention` while retaining the lease. Worktrees, logs and edits are preserved.
`kind="agent"` checks run sequentially through the configured verifier profile after the engine commit.
Their original instructions, fields, story scenario, exact base and previous problems reach each fresh verifier.
`problem` enters the reviewed fix loop; `on_fail="note"` and skips remain visible in questions. The first plan
is pinned across fixes, repeating failed checks and project tests. Reports and artifact paths are kept in
`verification.details`, and verifier calls appear in token statistics with `role="verifier"` and `check_name`.
Skills resolve from Codex project/user skill directories and plugin packages, not Claude-only installations.
Verifiers can create runtime artifacts under `.auto-bmad/`, but changing tracked code, the index or HEAD fails
the run. Built-in mockmatch uses a scoped browser tool RPC: the model stays in its sandbox, and the host
accepts only mockmatch operations and the configured `serve`/`url`, without arbitrary shell commands or installs.
Missing server fields use the host web detector; the CLI comes from a user/plugin installation outside the project.
Browser state and boards live in the protected session `browser/` folder; the model cannot forge cleanup PIDs. Deferred arbitrary shell cleanup is never run by the host: custom verifiers and adbm clean up before
returning; built-in mockmatch browser/server cleanup also runs on cancellation and host death.
Codex sandbox, network permissions, hook trust and missing browser/device dependencies remain enforced.
Conditional review layers remain unsupported.

### Prepared snapshot and standalone handoff

```bash
auto-bmad engine inspect --repo /path/to/project
auto-bmad engine prepare --repo /path/to/linked-worktree --output /new/package --level normal
auto-bmad run --manifest /package/manifest.json --arg "1-3" --allow-model --timeout 3600
auto-bmad agent execute --manifest /package/manifest.json --request /path/request.json --allow-model
```

`doctor` probes version/help without a model. `engine inspect` validates the contract and hashes; `prepare`
writes an auto-bmad-owned profile and runs the renderer offline through `uv`, without lifecycle hooks or models.
Human profiles and symlinks are preserved. `--output` must be new with an existing parent. Snapshot, config,
profile and engine hashes are rechecked at handoffs and commits. `execution_ready` is bound to the saved
[live receipt](../multi-agent/CODEX_STORY_SMOKE.json) and engine fingerprint; it does not prove current model
access (`inference_checked=false`). Another fingerprint cannot inherit this smoke's readiness.
Renderer failures preserve logs and the generated profile.

Standalone requests contain `role`, `task_id`, `base_commit` (full current HEAD) and `prompt` (original handoff).
They require a linked worktree; the main tree is refused. Role bodies come from `agents/` without Claude frontmatter.
Reviewers require read-only. Malformed results, reviewer writes, branch changes and rewriting the base fail.
Read-only fingerprints include submodules. Leaf success alone never proves `story_completed`.
Controller sessions also support `execute-batch`, `checkpoint`, `commit` and `rollback`. Without a session
or explicit `--allow-model`, a new model does not start.

### Separate transport smoke

```bash
auto-bmad agent-smoke --model <exact-model-id> --allow-model --timeout 60
```

One read-only Codex CLI in a new temporary Git repository, preserving private logs. This is not a BMAD story
or a merge. Live model calls are explicit and may consume model quota.

## stub

Background servers of a check: an API stub, a backend. See
[Checks](checks.md#background-servers-of-a-check).

```bash
auto-bmad stub start <name> [--port N] [--wait 30] [--run ID] [--repo .] -- <command> [args…]
auto-bmad stub stop <name> [--repo .]
auto-bmad stub stop --all [--runs-only] [--repo .]
auto-bmad stub list [--repo .]
```

`start` runs the command without a shell (shell syntax: `-- sh -c '…'`) in the repository,
in its own process group, logs to `.auto-bmad/stubs/<name>.log` and records `pid`, `pgid`,
the command, the port and the start time in `.auto-bmad/stubs/<name>.json` of the main tree
(also from a worktree). With `--port` it refuses a taken port and waits up to `--wait`
seconds until the port answers. The same name with the same command alive — `started: false`;
with another command — code 2. The command exited or the port did not answer — code 2 with
`log_tail`; whatever of the command still lives is killed then (`killed_group`). A command
that exits and leaves its group alive (it daemonizes) is recorded by the group
(`leader_gone`). The record also has the owner: `tree` — the working tree it was started
from, `run` — `--run` or `$AUTO_BMAD_RUN` (empty — started by hand). `ps` is read with
`LC_ALL=C`, whatever your locale.

`stop` checks that the recorded process still has the recorded pid, start time and process
group; the command line is only reported. A process that got the same pid later is left
alone (`note`). The leader gone, its group is stopped only while every member started after
the stub. TERM to the group, KILL after 5 seconds, then — only for a stub it stopped — up to
10 seconds for the port to be free (`port_free`). When `ps` cannot tell, the record is kept.
`stop --all` stops the stubs of its own working tree (another tree's are in `kept`);
`--runs-only` — only those with a run, which is what `story-finish` calls. Code 1 — a bad
name; code 2 — a stub of ours did not stop, its port stayed busy, its state is unknown, or
its record is broken (`error`). `list` — the recorded stubs with `alive`, `tree` and `run`.

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
auto-bmad stats show [--epic N] [--last N] [--calls] [--json] [--repo .]
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

0. `stop stubs` — `stub stop --all --runs-only`: background servers a check left; the step shows only
   when it stopped something or failed;
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

## evidence

Code excerpts for all review findings of a pass in one call. The engine session (or the
triager subagent) calls it during triage instead of a `grep` or `git diff` per finding: fact H
of the level profile asks for it.

```bash
auto-bmad evidence --input .auto-bmad/evidence/<spec>.json [--base <rev>] [--context 3] [--repo .]
```

Input — a JSON file written with the Write tool:

```json
{
  "base": "<baseline_revision>",
  "findings": [
    {"id": "1", "file": "src/a.py", "lines": "40-52"},
    {"id": "2", "file": "src/b.py", "lines": "12", "diff": true},
    {"id": "3", "file": "src/c.py", "grep": "parse_date\\(", "grep_in": "."}
  ]
}
```

Per finding: `lines` — `"12"`, `"40-52"`, `"12,40-52"` or a list; `diff: true` — the hunks of
`git diff <base> -- <file>` that touch those lines; `grep` — a regular expression for
`git grep -E`, in `grep_in` (a path, `.` — the whole repository; the finding's file by
default). The answer has, per finding, `code` (numbered lines with `--context` lines around
them), `diff`, `grep` (`hits`, `count`) and `error` for a part that failed. Excerpts are cut at
120 lines, grep hits at 20. A finding's own error does not fail the call; code 1 — no input
or broken JSON. The command excludes `.auto-bmad/` from git, so the input file does not make
the tree dirty.
