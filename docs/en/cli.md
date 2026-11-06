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
| `native` | `native_session.py` |
| `engine` | `engine.py` |
| `stub` | `stub.py` |
| `test` | `testrun.py` |

## setup

Project state by stages and writing of settings. Asks nothing; without `--write` writes nothing.
See [Install](install.md#set-up-a-project).

```bash
auto-bmad setup check [--repo .]
auto-bmad setup agent --agent codex [--model MODEL] [--effort high] [--review-model MODEL] \
    [--review-effort E] \
    [--disable-agent-checks] [--layer project|local] [--add|--select] [--compact|--advanced] [--level fast|normal|deep] [--role ROLE] [--repo .] [--write]
auto-bmad setup agent --agent claude [--layer project|local] [--add|--select] [--repo .] [--write]
auto-bmad setup init [--repo .] [--level normal] [--parallel conservative] [--width 3] \
    [--android-module <m>] [--no-android] [--test-command CMD] [--write] [--force]
auto-bmad setup headless [--repo .] [--write] [--force]
auto-bmad setup allow [--repo .]
auto-bmad setup role --role <role> [--model M] [--effort E] [--layer project|user|local] [--repo .] [--write]
auto-bmad setup local [--repo .] [--write]
```

`check` — stages `env`, `bmad`, `plan`, `project`, `execution`, `extras`, `headless` and `next`.
It lists clients in `agents`. `execution` checks settings and workflow files without models, tests or hooks.
Native tool availability is checked separately in the active chat.
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

**Client setup.** `$auto-bmad-setup` in Codex and `/auto-bmad:setup` in Claude use the same
configuration helper. The active frontend identifies its client; a standalone invocation can use
`--executor codex|claude`. Setup does not infer the client from installed executables.

`setup agent` previews model settings for the current client. It defaults to private
`.auto-bmad.local.toml`; explicit `--layer project` retains shared settings support.
`[executors.codex]` and `[executors.claude]` coexist; changing one preserves the other.
Common tests, hooks and run rules stay in project configuration. Tracked local files are refused.

Use `--add` to preserve the stored backend, `--select` to change it explicitly, and `--write`
to apply the preview. The Codex wrapper supplies its client and `--add`; new `init` establishes
the initial project default. Repeated setup reuses existing model/effort choices.
`--level fast|normal|deep` changes one level; `--role <id>` changes one actual subagent's model/effort.
IDs are `story-runner`, `implementer`, `context-compiler`, `blind-hunter`, `edge-case-hunter`,
`intent-alignment`, `verification-gap`, `triager`, `verifier`. Review layers have separate settings.
For example: `setup agent --agent codex --role blind-hunter --model gpt-6-astra --effort high`.
Add `--level deep` to affect that subagent only on deep. Unknown subagent/layer IDs require
explicit support; no generic reviewer fallback is used.
Prefer `init` for common project settings, then `agent` for private client settings. `--compact` converts compatible advanced Codex
routes with a backup; unsupported adapters and incomplete routes fail rather than switch models.
The old `--executable`, `--env` and `--timeout` options are not supported in native mode.

Defaults and precedence are described in [configuration](config.md#compact-codex-models).
Model names belong to the client adapter; Claude aliases are not translated into Codex IDs.
Reviewers receive no-edit instructions but inherit the parent chat's permissions.
Agent checks such as adbm/mockmatch remain enabled unless explicitly disabled by the user.
`--disable-agent-checks` records an explicit opt-out and never changes checks implicitly.

Before writing, setup validates all layers and refuses conflicting overrides. It writes atomically,
preserves unrelated TOML values and backs up changed existing files under `.auto-bmad/setup-backups/`.
`init` never migrates an existing file with `--force`; use `agent`. Native Codex `headless` reports
that an active chat is required. Claude retains its headless permissions workflow. Setup never starts models.

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
auto-bmad verify attempt --kind tests --story 1-3 --base <sha> --level normal --result-file failed.json [--repo .]
auto-bmad verify observe --story 1-3 --base <sha> --result-file rerun.json [--repo .]
auto-bmad verify fix-spec --spec <path> --pass N [--repo .] < problems.md
auto-bmad verify fix-spec --spec <path> --pass N --problems-file F --commit-story 1-3 [--repo .]
```

`plan` — which checks apply to the story diff (`verifiers`, `skipped`, `fix_limit`).
`baseline` — runs the project tests once and stores the result. `run` — runs a
`kind = "command"` check and returns `verdict`. `attempt` counts a repair in its independent
`spec`, `review` or `tests` category (`--kind`, default review). Tests require the failed result
JSON and a subsequent `observe` of the same command. Three attempts without progress block.
The Codex native journal records its own check/repair evidence; Claude retains these helpers. `fix-spec` is a manual
spec-editing tool, not the test repair route: it adds fix tasks to a `done` spec and moves
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

<a id="cli-backend-codex-and-sequential-epics"></a>

## Native Codex orchestration

The main chat routes bounded tasks, slots, dependencies and user decisions. All substantive
work runs in fresh isolated native subagents, including bootstrap, planning, diagnosis,
triage/revalidation, test execution/waits, integration and final reporting. The root reads no
source, diffs, full reports/journals or logs. Existing configured role models/effort remain.
The Python interface supports planning, state and evidence; it never starts models or schedules stories. The previous `run`, `agent`
and `agent-smoke` execution entry points are removed. There is no CLI fallback.

```bash
auto-bmad --executor codex native task-prepare --repo /path/to/project --arg "epic-1 --normal" --checkpoint bootstrap --host-limit 4 --root-thread-id <actual-root-UUID> --root-turn-id <actual-turn-UUID>
auto-bmad --executor codex native task-prepare --session /private/session.json --story 1-1 --role triager --checkpoint revalidation --input /private/handoff.json
auto-bmad --executor codex native task-start --task /private/task.json --agent-id actual-host-id
auto-bmad --executor codex native task-result --task /private/task.json --agent-id actual-host-id --confirm-completed
auto-bmad --executor codex native task-stop --task /private/task.json --agent-id actual-host-id --status failed --reason "observed host failure" --confirm-terminal
auto-bmad --executor codex native plan --repo /path/to/project --arg "epic-1 --normal"
auto-bmad --executor codex native init --repo /path/to/project --arg "epic-1 --normal"
auto-bmad --executor codex engine prepare --repo /path/to/worktree --output /private/new-manifest --level normal
auto-bmad --executor codex native record --session /private/session.json --request /private/event.json
auto-bmad --executor codex native record-batch --session /private/session.json --request /private/batch.json
auto-bmad --executor codex native summary --session /private/session.json --story 1-1
auto-bmad --executor codex native status --session /private/session.json
auto-bmad --executor codex native check --session /private/session.json --story 1-1
auto-bmad --executor codex native resume --session /private/session.json
```

Bootstrap `task-prepare` requires `--host-limit` from the live host's actual total capacity
(the example's 4 applies only to a four-slot host). Pass paired actual `--root-thread-id`
and `--root-turn-id` when exposed; otherwise supply `--accounting-unavailable-reason` with
the real reason. These become persisted `host_metadata`; never invent UUIDs or silently
omit unavailable accounting. Public `--fast`/`--normal`/`--deep` flags and configured defaults
keep their existing meaning in `--arg`.

`task-prepare --checkpoint bootstrap --planning-only` delegates a planning-only request
without initializing a session or mutating worktrees; its `created_session` must stay null.
`task-prepare` persists task inputs and returns a bounded `spawn` envelope with the configured
model/effort and `fork_turns: "none"`. Root spawns it, then `task-start` binds the actual host
agent ID. The worker calls `task-binding --task TASK --wait-seconds 60` once before work;
it waits locally for the saved binding, without an extra root message. On timeout or
cancellation it stops and reports. Each worker reads full inputs directly and writes the
exact `receipt_template`, with current tree and artifact hashes.
`task-result` requires actual observed terminal completion before `--confirm-completed`; it
checks identity/provenance, not story acceptance. Helper output is capped at 4096 UTF-8 bytes,
receipt at 16384 bytes, four short actions and eight artifact references. Full reports remain
on disk. A malformed result goes to a fresh specialist, not root source inspection. Remaining
planning/check/finish commands are specialist work. If the actual host reports failed/stopped
without a usable receipt, `task-stop --status failed|stopped --reason <observed-reason>
--confirm-terminal` records that terminal task while preserving history. Join the actual
agent first; this helper cannot terminate a live agent or claim success. Bounded technical
retries may proceed from preserved work; explicit cancellation cannot resume automatically.
For an actually completed host agent with a missing/invalid receipt, use `task-stop --status
failed --host-status completed --reason <receipt-failure> --confirm-terminal` with its actual
task/agent IDs. The journal records agent completed and task failed, without inventing a
receipt or accepting evidence. Host completed pairs only with task failed, never stopped;
a fresh authorized task requires that explicit native terminal observation.
See [root routing](../../skills/auto-bmad/ORCHESTRATOR.md).

Use the session and manifest paths returned by the helpers; these examples are placeholders.
`native init --plan <file>` accepts the complete saved `native plan` result and revalidates it.
Session state lives in shared Git metadata, outside tracked source files. It records story bindings,
agent IDs, phases, repair counts, reports and check receipts. A completed report alone is insufficient:
`complete` requires the done spec, clean committed worktree, current reviews and command results.
It marks the branch verified, with finalization pending. A finite finalizer inspects the
actual finish artifacts and current evidence, saves a record-batch request for `complete`
and/or `finalize`, and returns `ready`. It never applies its own completion while running.
Root observes terminal completion, calls `task-result`, then mechanically submits the saved
request path from the bounded receipt through `record-batch --request`; no root technical
acceptance occurs. Integration/finish work and final-root `check` receipts must be complete
before requesting `finalize`. Gates validate tracking, ancestry, current evidence, clean
worktree and absence of active agents. Rejection requires a fresh specialist. Changed merged code needs a scope/risk assessment: fresh reviews for extensive/risky changes, explicit targeted revalidation otherwise.

`native record` receives JSON events: `schedule`, `bind`, `phase`, `agent`, `review`, `review-revalidate`, `review-not-applicable`, `repair`, `retry`, `complete`, or `finalize`.
New native plans require a dependency `schedule` before binding, including singleton waves
for serial/single-story runs. New sessions use `orchestration_policy: "thin-root-v1"`;
old journals retain policy, topology and pinned runtime. No automatic migration occurs.
For `review-revalidate`, `evaluated_by` is the completed registered triager ID, also bound in
JSON evidence to story/layer/source/target trees and complete closure evidence. Conditional
`review-not-applicable` needs a completed story-runner/triager ID and matching JSON condition,
false result, target tree and nonempty rationale. The gate rechecks provenance and hashes;
`main-chat` evaluation remains only in legacy sessions.
`native record-batch` receives `{"batch_id":"unique-stable-id","events":[...]}` and commits
all events atomically through the same gates. Identical retries return the original compact
receipt without applying events twice; changed content with the same ID is rejected. The receipt's
event offsets are not a revision of check results. `record` retains its full-state response.
`native summary` returns compact navigation without full history or test output; `--story` adds
that story's fresh fingerprint. Recorded verdicts/tree matches are not evidence validation.
Full findings and diagnostics remain in the canonical journal and referenced reports/logs.
The Codex root uses the longest allowed interruptible event wait (API maximum currently
3600000 ms), never minute polling. Generic 60-second blocking-shell guidance is not a cap on
this interruptible API. Explicit hard host caps still apply and must be reported; their
necessary timeout wakeups cannot be disabled by this passive helper. Finite verifiers own
managed test/session waits and honor actual blocking-tool limits without hidden wait loops.
The exact fields and native agent handoff are in [NATIVE.md](../../skills/auto-bmad/NATIVE.md).
`native check` executes configured command verifiers and returns required native agent verifiers.
Device/browser verifiers use the installed adbm/mockmatch skills and their native capabilities.

`native status` cannot infer whether an app agent is alive. Reconcile saved IDs through the actual
native tools before resuming. `native cancel` only records cancellation; the orchestrator must stop
and join active agents. A cancelled run requires explicit user instruction before
`native resume --confirm-cancelled`. Resume never resets repair counts or spawns a model.

For an authorized host-owned heartbeat, `native host-bind --session <session> --request <json>`
stores the actual `thread_id` and `automation_id` in `host-continuation.json` beside the journal.
Register through the host first; this helper does not create an automation. Rebinding is
idempotent and cannot change ownership. `native host-recover` takes the same IDs plus the
preceding `turn_id`, normalized `turn_status`, and confirmed `cause`; it returns `continue`,
`wait`, `already-claimed`, or `stop`. Interruptions and human blockers disarm recovery.
The saved `technical_limit` bounds root-turn recoveries between finalized stories, separately
from story retries. Fresh human resumption can rearm the same binding through `host-bind`
with `resume_authorization_turn`; it preserves the budget. Host observations and actual
pausing/reactivation remain the adapter's responsibility. See the
[Codex continuation contract](../../integrations/codex/skills/auto-bmad/CONTINUATION.md).

Native roles inherit parent permissions; review instructions do not create a separate read-only
sandbox. Models/effort come from `agent-config`, and native tools must support those choices.
`doctor` validates configuration and workflow files, not a live model or agent-tool call.
Native statistics can import per-response usage from explicitly bound local Codex rollouts; see [statistics](stats.md). Missing measurements remain unavailable; old CLI receipts do not validate this mode.

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


### Thin-root receipt preflight and compact acceptance

`native task-binding --task TASK --wait-seconds 60` waits locally once for the real
start binding; timeout/cancellation means stop, not a model polling loop.
`native task-receipt --task TASK --request DECISION` builds `result.json`; DECISION has
`state`, `next`, `actions`, `blocker`, `artifact_paths`, optional `created_session`.
`native task-preflight --task TASK --agent-id ID [--receipt FILE]` checks an existing receipt
without saving a terminal state. Both accept `--record-batch FILE` to preflight a hashed
same-story batch against current gates with only this producer's completion simulated.

After observing actual host completion, root can combine registration and journal application:
`native task-result --task TASK --agent-id ID --confirm-completed --record-batch FILE`.
The batch must be a hashed receipt artifact; it cannot bind stories or change agent liveness.
Gate rejection reports `receipt_accepted=true`, `batch_applied=false`, `state=blocked`;
no batch event is saved, and a fresh specialist handles diagnosis. Terminal registration
is retained. Never infer successful completion from command exit code alone.

`verify plan --working-tree ...` includes committed, staged, unstaged and untracked files
for detection. Native thin-root journal checks select this automatically; older journals
keep their original behavior. No model configuration or review/check requirement changes.


## Verification frequency for new native sessions

New sessions save `verification_policy="integration-full-v1"`; existing journals keep their
original gates. During implementation and repairs run registered focused tests plus
compile/build checks. Do not run the full suite or a full baseline by habit, after each
review, or once per story when stories will land together. `native check --session SESSION
--story ID --request PLAN.json` persists development evidence and validates fixed registered
commands. PLAN contains `checks` (objects with development check `name` and `targets`) and
`builds` (all registered build names). Names resolve from `project_tests.development` and
`project_tests.build`; no command is generated from source filenames. Missing focused
coverage is a blocker. If no build exists, save an explicit `build_not_applicable` reason;
registered builds cannot be skipped. A concrete `full_risk` explanation permits an early full
project check only when broad/architectural risk makes it necessary. It is not a routine
preparation step. Full baseline execution is not part of this policy.

`complete` needs current focused/build evidence and all mandatory independent/agent reviews;
it marks a story ready for integration, not ready to move main. The full gate runs on the
combined candidate **before main changes**, preferably once for all stories in that landing:
`auto-bmad land BRANCH --native-session SESSION --story ID [--story ID ...]`. This extends the
existing guarded merge-candidate worktree pipeline; it never changes the selected landing
mode. It checks every selected mandatory command, the full registered `project-tests`, and
registered builds. `--no-tests` is forbidden for this policy. Preserve story worktrees until
journal finalization. Never substitute a raw Git merge for this guard in an automatic run.
A different main HEAD after checks requires a new candidate.

Exact candidate code, config, command/timeout set and saved log hashes allow a successful
integration gate to be shared across included stories and reused at finalization. A changed
merge resolution, command, config or evidence invalidates reuse; a child branch pass alone
does not certify the combined candidate. Saved evidence lives in journal metadata even when
the temporary candidate worktree is removed. For an existing candidate, the finite verifier
can run/join `native integration-check --session SESSION --repo CANDIDATE --story ID ...`.
A running result is not a pass. After a failed full gate, repair the complete failure set,
then run focused regressions/build on the repaired candidate with `native check --repo
CANDIDATE --request PLAN.json ...`, then rerun the final full gate. A failed full gate cannot
immediately trigger another full execution without this current focused evidence.

Wave/dependency barriers and the configured landing mode are unchanged. One full gate per
whole epic applies when that epic has one combined landing; separate authorized landings
need their own exact-candidate proof. Do not silently combine landings or weaken reviews,
mandatory checks, clean-tree, ancestry or finalization requirements to reduce run counts.


```toml
[project_tests.development.unit]
command = "python3 -m pytest"
targets = ["tests/test_*.py"]
[project_tests.build.compile]
command = "python3 -m compileall -q app"
```

```json
{"checks":[{"name":"unit","targets":["tests/test_feature.py"]}],"builds":["compile"]}
```

These are configuration examples, not inferred commands for an unknown project.

Bounded native sessions additionally expose `local-check --task --request`,
`repair-route --session --story` and `context-publish --task --artifact`. Journal
events `repair-batch`, `repair-amend` and `repair-close` require a completed triager
and hashed decision artifacts. See [schemas and lifecycle](../../skills/auto-bmad/CHECKPOINTS.md).
