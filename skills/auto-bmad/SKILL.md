---
name: auto-bmad
description: 'Runs a story or a whole epic through BMad v6 automatically: each story goes to its own bmad-story-runner subagent (spec → code → review → tests → commit), so context does not pile up between stories; by default the stories of an epic run in parallel waves, each in its own git worktree, and are merged back (--parallel-fast — aggressive selection, --no-parallel — one at a time). The skill syncs sprint-status.yaml, collects the open questions of the epic in one file and gives a report. Review depth is set by the level --fast / --normal / --deep. Needs BMad v6 in the project: the bmad-build-auto skill, _bmad/scripts/render_skill.py and sprint-status.yaml, plus the bmad-story-runner agent type.'
disable-model-invocation: true
argument-hint: '[story-id | epic-N | empty] [--fast | --normal | --deep] [--parallel-fast] [--width N] [--no-parallel]'
allowed-tools: Read Write Edit Glob Grep Agent TaskCreate TaskUpdate TaskList TodoWrite Bash
model: opus[1m]
effort: medium
---

# BMad Auto — run a story or an epic through BMad v6

A thin orchestrator on top of `bmad-build-auto`. It does not write or review code itself:
the whole cycle lives inside the engine. This skill owns the story queue, the run depth,
the sprint tracking sync, the open questions of the epic and the report to the human.

**Each story runs in its own `auto-bmad:bmad-story-runner` subagent.** For one story the
engine generates tens of thousands of tokens — spec, diff, review layer reports, triage of
findings — and in one context this would pile up: by the end of the epic the last stories
would run slow and expensive. The subagent cuts this off: the run's noise lives and dies
inside it, and only the finished report comes back.

## Skill files — what to read when

The mechanics live in scripts, and rarely needed texts live in nearby files. Read them
when needed, not in advance.

| File | When |
|---|---|
| `LEVELS.md` | you need to explain a level to the human, or understand the review layer layout or the limits |
| `REPORTS.md` | Step 4 (open questions file), Step 5 and the final report: rules and templates |
| `PARALLEL.md` | Epic mode without `--no-parallel` — that is, almost always |
| `auto-bmad <cmd>` command | called along the steps; do not read the script code, every subcommand has `--help` |

`auto-bmad` is this plugin's CLI from its `bin/`; it is in the PATH of every Bash call. A
subcommand runs a script from the plugin's `scripts/` through `python3` (stdlib only):

| Subcommand | Script |
|---|---|
| `plan` | `plan_run.py` |
| `preflight` | `preflight.py` |
| `profile` | `write_profile.py` |
| `spec` | `read_spec.py` |
| `sync` | `sync_sprint.py` |
| `questions` | `open_questions.py` |
| `window` | `window.py` |
| `worktree` | `worktree.py` |
| `ext` | `ext.py` — extensions: config, events, hooks |
| `stats` | `stats.py` — run statistics of the project |
| `story-finish` | `story_finish.py` — the finishing steps of a story or a wave in one call |
| `verify` | `verify.py` — checks after a story (Step 3.5) |
| `setup` | `setup.py` — project setup (the `/auto-bmad:setup` skill) |

Below, scripts are named both by command and by file name — they are the same thing. One contract for all: **JSON in stdout always**, on any outcome; the reason for a failure is
in the `error` field (for `preflight.py` — the `blocking` list) and is **repeated in stderr**,
so it is visible without parsing JSON. Exit codes: `0` — success, `1` — call error
(no folder, a required argument is missing), `2` — "not done by rule": the queue
is empty, the argument is ambiguous, the profile was written by a human, preflight found a blocker.
Exception — `ext.py fire` and `ext.py answer`: they return `0` on any hook outcome,
and the substance is in the response fields (the "Extensions" section below).

Commits belong to the skill, because only the skill knows what goes into each commit and
when the tree must be clean. Two scripts commit on the skill's order: `story-finish`
(the finishing steps, Step 4) and `verify fix-spec --commit-story` (Step 3.5).

## What the engine does and what this skill does

`bmad-build-auto` does **everything** for one story in one call and HALTs with a status:

| Inside `bmad-build-auto` | Inside `auto-bmad` |
|---|---|
| plans the spec (`spec-<slug>.md`) | parses the argument and level, builds the story queue |
| compiles `epic-<N>-context.md` | builds the level profile |
| implements the code in a subagent | preflight checks |
| review in parallel layers + triage + autofix + loopback | runs `auto-bmad:bmad-story-runner` on a story |
| runs `## Verification` from the spec | syncs `sprint-status.yaml` and commits the tracking change |
| **commits** and requires a clean tree on exit | prints the story report and builds the epic report |
| — | collects the open questions file of the epic |
| writes `## Auto Run Result` into the spec | in parallel mode — worktrees and branch merges |

The main point: **there is no separate code review, separate verify or separate code commit
here**. The engine does them before it returns control.

## Project requirements

`auto-bmad preflight` checks them — do not check by hand. Needed: the `bmad-build-auto` skill,
`_bmad/scripts/render_skill.py`, `_bmad-output/implementation-artifacts/sprint-status.yaml`,
the `_bmad/custom/` folder, `uv` in PATH and the `auto-bmad:bmad-story-runner` agent type.

Something is missing — tell the human and finish. Do not replace the engine with manual implementation.
Suggest `/auto-bmad:setup` in one line: it checks the project step by step and helps
install and set up what is missing (BMad, the plan, `.auto-bmad.toml`).

The skill needs **no** project engine settings: everything the run needs goes into the level
profile written by `write_profile.py`. The agent types (`auto-bmad:bmad-story-runner`, `auto-bmad:bmad-implementer`,
three reviewer types and `auto-bmad:bmad-compiler-lite`) come with the plugin and exist in any project.

## CRITICAL: language and style

- **Talk to the human in the run language** — and write reports and open question items in it.
- The run language is the `language` field from `auto-bmad plan` (BMad `communication_language`).
  Empty — use the language the human writes in. The run is unattended and the language is
  still unknown — English.
- Pass `Language: <run language>` in every `auto-bmad:bmad-story-runner` and
  `auto-bmad:bmad-verifier` prompt.
- Machine header fields, markers (`WORK_START`, `STORY_DONE`, …), event names, JSON keys and
  commit messages are English and fixed: never translate them.
- Report templates in `REPORTS.md` are written in English; render their headings and text
  in the run language.
- Technical terms (story, epic, commit, review, spec) may stay as they are.
- Tone: businesslike, no extra words.
- **Write reports as if the reader knows neither the project nor BMad** — rules in `REPORTS.md`.

## CRITICAL: one command per Bash call

A run without a human (a bot, `claude -p`, auto mode) has nobody to approve a command.
The auto mode classifier then checks every Bash call as a whole, and at times it denies a
long chain. A denied chain loses every part of it: the commit, the sync, the hook events
and the statistics together. So:

- **one `auto-bmad` call per Bash call.** No `&&`, `;`, `for` loops or `set -e` around it;
- **never pipe `auto-bmad` output into `python3 -c`, `jq` or `grep`.** The JSON comes back
  to you as the call result: read the fields yourself;
- **no heredoc.** Text for a script (open question items, check problems, the finishing
  input) goes into a file under `.auto-bmad/finish/` with the `Write` tool, and the command
  gets the path. The folder is excluded from git, so the files do not make the tree dirty;
- **the finishing steps of a story are one command**, `auto-bmad story-finish` (Step 4).
  It writes the questions, syncs the sprint, commits, fires the hook events and records
  the statistics; a failed step does not stop the others, and its result is in `steps`.

## FORBIDDEN

- Running a review after the pipeline is done: the engine reviewed everything before the commit.
  A general "review before handing over a task" rule from the project's or the user's
  instructions is covered here.
- Implementing a story yourself, bypassing `bmad-build-auto`.
- Calling `bmad-build-auto` as a skill in your own context: the engine runs only inside
  the `auto-bmad:bmad-story-runner` subagent. A direct call brings back exactly the problem the
  subagent exists to solve.
- Reading the spec, the diff and `## Auto Run Result` yourself: the story report is built by the
  subagent, which already has this material in its context.
- Doing by hand what a script does: parsing the argument, filtering the queue, writing the
  level profile, editing `sprint-status.yaml` and the open questions file, looking for the spec.
- Editing code beyond what the engine did. This skill writes only through scripts:
  `sprint-status.yaml`, `_bmad/custom/bmad-build-auto.user.toml`,
  `<questions_file>` and — by commit — the files a hook returned in the `files` field
  (the "Extensions" section).
- Editing the project's `_bmad/custom/bmad-build-auto.toml`: it holds the project's permanent settings.
- Continuing the epic after `STATUS: blocked` from the subagent.
- Stopping in Epic mode while there are unfinished stories — except HALT conditions
  and a `take_next: false` answer from `window.py` at Step 6 (in parallel mode — P6).
- **Abandoning a started story because of time.** The time window is checked only between
  stories; the one you have already started is always brought to the commit, sync and report.

## Time window

The run can go inside a limited time window: an external runner (cron, CI, a scheduler)
may give it one. You **do not see or count** the window yourself: only
`auto-bmad window` knows about it, and it is asked once per story, at Step 6 (in parallel
mode — at Step P6). The rule is simple: **what was started is always finished**; the window
decides only whether to take the next story. A run started by hand has no window —
the script then answers "take it" by itself.

The same script also guards the **subscription limit**: the usage of the five-hour and weekly
windows comes to it in a snapshot from the runner that watches the stream, and the threshold
comes from the runner's config. The refusal reason is then different, but the behavior is the
same: what was started is finished, the next one is not taken. You do not see the limit numbers
either, and do not write them into the report yourself — take the wording from `reason`.

## Step 0 — Scope, level, profile

```bash
auto-bmad plan --arg "<the skill argument as is>"
```

Returns JSON: `level`, `parallel` (`off` / `conservative` / `aggressive`), `parallel_width`,
`mode` (`epic` / `story`), `epic`, `epic_title`, `story`, `stories` (the queue, already
sorted and cleaned of `done` and the retrospective; each has `title` and `goal`
from `epics.md`), `count`, `language`, `questions_file`, `warnings`, sometimes `note` and `waiting`.
Story numbers are strings as in BMad's keys: `"3"`, or `"6a"` for a split story. Use the ids
(`stories[*].id`, for example `2-6a`) as they come, in every command and prompt below.

**Keep `language` and `questions_file` for the whole run.** `language` is the run language
(the "CRITICAL: language and style" section). `questions_file` is the path of the epic's open
questions file relative to the repository; wherever the steps below say `<questions_file>`,
use this path. Do not build the file name yourself.

- `waiting` is not empty together with `error` — the epic or story waits for an unmet condition
  from the "**Waits:**" line of the epic in `epics.md` (another epic or story is not `done`, or
  a condition in words that the script cannot check). This is **not** an ambiguity:
  ask nothing and do not start the run. Show the human the line
  `Epic <N> not started: waits for <waiting items joined with "; ">` (for one story —
  `Story <id> not started: …`) and finish normally. An unattended run — the same.
- `error` in the JSON (code 2) without `waiting` — **do not guess**: show the text to the human and ask
  what was meant. Do the same with two level flags and with an unparsed scope.
- `waiting` is not empty without `error` — the queue is cut: one of the epic's stories waits for
  something unmet, and the run goes only up to it. The reason is in `note`. Say it in a line
  before the run table and repeat it in the final epic report, under "Needs attention":
  what was left undone and what it waits for.
- `note` — the script made a non-obvious decision (for example, no stories were left in
  `in-progress` epics and the first `backlog` story of the next one was taken). Tell the human in a line.
- `warnings` is not empty — the human used a removed flag (`--parallel`), `epics.md`
  did not parse and the titles in the run table will come from slugs, or a numbered heading
  is outside BMad's `## Epic N:` / `### Story N.M:` format and was not read. The run goes on,
  but say the warning in a line: silently taking the default wave width instead of the
  requested one is the worst option.
- `mode: epic` — the queue is in `stories`, its length is `M`. `mode: story` — work on one.

### Extensions — run start

Personal and project additions (a task board, notifications) are connected as hooks in the auto-bmad
config; the rules for talking to them are in the "Extensions" section below. Once per run, before
preflight, tell the hooks about the start:

```bash
auto-bmad ext fire run-start --epic <N> --level <level> --repo .
```

No hooks — the answer has empty `results`, go on silently. Tell the human the `message` lines from `results`
as they are. The `asks` field holds hook questions to the human:

- `asks` is empty — go on. An unattended run (a time window, `AUTO_BMAD_UNATTENDED=1`)
  never gets `asks`: `ext.py` drops them itself.
- for each question — `AskUserQuestion` before the first story: text `question`, options —
  `options[*].label` with `description`. Pass the answer to the hook:

  ```bash
  auto-bmad ext answer --hook <hook> --option <id of the chosen option> --repo .
  ```

  The human answered something else ("later", "not now") or there is no way to ask (`claude -p` without
  a human, `AskUserQuestion` not available) — pass nothing, the hook will ask next time.

The `files` field in the `fire` or `answer` response is not empty — the hook created files in the tree. Commit
**only them**, otherwise the next preflight stops on a dirty tree. The files are new, so
`git add` first, and the commit lists the paths so it does not pick up anything else from the index;
the message is the hook's `message`:

```bash
git add -- <files> && git commit -m "<hook message>" -- <files>
```

Then — **preflight** (Step 1), and only after it the level profile. The order matters:
the profile lives in the working tree, and if you build it before the check, you make the tree
dirty yourself, and preflight shows the human a file the skill has just created.

The profile is built **once for the whole run**:

```bash
auto-bmad profile --level <level> --repo .
```

- code 2 — the file was written by a human: show the path, say that you cannot apply the level
  without overwriting someone else's setting, and finish;
- code 1 — no `_bmad/custom/` folder, the project does not look like BMad v6, or the `[roles]`
  config has errors (the `error` field): report and finish;
- `agent_args` in the response — the model and effort the project owner set for roles in
  `[roles.*]` of the config. Remember it for the whole run: when you launch
  `auto-bmad:bmad-story-runner` or `auto-bmad:bmad-verifier` and `agent_args` has that role
  (`story-runner`, `verifier`), pass its `model` and `effort` as parameters of that `Agent` call.
  A role that is not in `agent_args` — launch without them. The engine's own subagents get theirs
  through the profile; do not pass them anything;
- `git_excluded: false` in the response — the profile could not be added to `.git/info/exclude`,
  the tree will count as dirty: tell the human in a line.

Name the level to the human in one line before the first story — it sets both the time
and the depth of checking. The layer layout and limits are in `LEVELS.md`; read it only if you need
to explain more.

```
Level: normal — three review layers, up to 2 review passes and up to 2 fix cycles per pass.
```

**Test baseline — right after the profile, once per run** (not needed on `fast`: there are no
checks after a story there). The check step (Step 3.5) needs it: a test failure after a story
counts as the story's breakage only if the tests were green before the run.

```bash
auto-bmad verify baseline --repo .
```

Code 2 — the `project-tests` check is off or there is no test command: go on silently.
`verdict: problem` — the tests are already red: tell the human in a line that tests fail
before the run and the check step will not fix them.

**Parallel is the default behavior in Epic mode.** There is no separate "turn on" switch:
`plan_run.py` returns `parallel: conservative` unless the human said otherwise.
`--parallel-fast` switches story selection to aggressive, `--width N` sets the wave size
(3 by default), `--no-parallel` turns parallel off completely.

- `parallel != off` and `mode: epic` — read `PARALLEL.md` and follow it from there.
- `parallel: off` — Steps 1–6, one story at a time.
- `mode: story` — parallel turns off by itself, the steps are the same.

### Run table — before the first story

The human must see at a glance what was taken into work and what each story
does. So right after the level line, before the first `WORK_START`, print a table.
The story titles and goals are already in `stories[*].title` and `stories[*].goal`
(`plan_run.py` takes them from `epics.md`), the epic name is in `epic_title`; do not retell
them in your own words and do not read `epics.md` for the table. Empty `goal` — put `—`.

**Stories go one at a time** (`parallel: off`, `parallel_ready: false` from the parallel
preflight, one story in the queue, Story mode):

```
Epic 16: Improvements from usage — 2 stories, one at a time (<why not in parallel>)

| # | Story | What it does |
|---|---|---|
| 1 | 16-1 · The keyboard does not cover input fields | so that the field stays visible with the keyboard open… |
| 2 | 16-2 · Reminders on the home screen — at most once a month | so that reminders do not pop up again and again… |
```

The reason in brackets — only when parallel was possible but is not used: `--no-parallel`,
the engine is outside git (in your own words from `engine_untracked[*].fix` of the parallel preflight),
one story in the queue. In Story mode there are no brackets, and the heading is `Story <id>`.

When to print: with `parallel: off` and in Story mode — right after the level line.
On fallback from parallel (`parallel_ready: false`) — right after the parallel preflight
(Step P0 of `PARALLEL.md`), before the first `WORK_START: story`: only there is the reason known.

**Stories go in waves** — the table is different, with waves: its format is in Step P1 of
`PARALLEL.md`. There too, in Step P2, is the table of stories launched together,
at the start of each wave.

### Task list — required in both modes

The run is long, and the human follows it in the interface. **The task list is always created**,
before the first engine call. Tool: `TaskCreate` / `TaskUpdate` / `TaskList`,
and if they are not in the session — `TodoWrite`.

**Epic mode** — a task for each story in the queue plus a final one:

| Field | Value |
|---|---|
| subject | `Story <id> (<N>/<M>): <title>` |
| activeForm | `Story <id> (<N>/<M>): <current step>` |

The last task — `Epic <N>: final report`.

**Story mode** — a task per step: `Preflight`, `Story run`, `Check`, `Sprint sync`, `Report`.

Task names and `activeForm` texts go in the run language. Rules:

- Exactly **one** task is `in_progress` at any moment.
- A story task goes to `in_progress` at Step 1 and to `completed` at Step 5.
- Update `activeForm` at each step: `Preflight` → `Run in an isolated context`
  → `Check` → `Sprint sync` → `Report`. The steps inside the run happen in the subagent, there is no way
  to update the task from there — this part is not detailed in the interface.
- The story went to `blocked` — leave its task `in_progress` and do not close it: it is not done.
  Do not touch the other tasks of the queue; their open state is the report of what was not done.

No task tools in the session at all — do not fail: track progress
as text by the "Progress bar" section rules and tell the human in one line that there will be no
task list in the interface (it is turned on by the `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` variable in
`~/.claude/settings.json`).

## Step 1 — Preflight

```
[Story N/M] ⏳ Preflight → ⬚ Story run → ⬚ Check → ⬚ Sprint sync → ⬚ Report
```

**The first line of the step is the machine marker of the story taken into work**, verbatim
and on its own line:

```
WORK_START: story <id>
```

An external runner that watches the stream reads it: from it the runner sees what was taken
into work after the end of the time window, and stops the run if the window was ignored. The progress
bar does not work for this — in parallel mode there is none at all.

```bash
auto-bmad preflight --repo . --level <level>
```

`--level` lets the checks after a story run their own preflight: for example, mockmatch with
`design_project` asks whether Claude Design is logged in, and without the login and a saved copy
of the design it is a `blocking` line. `blocking` is not empty (code 2) — show the list to the human and stop; no BMad, engine or
`sprint-status.yaml` — suggest `/auto-bmad:setup`. A dirty tree — show the
files and let the human decide whether to commit or revert: do not commit or revert someone else's work yourself.
`warnings` — name them in a line and go on. Code 1 — the given folder does not exist, check the path.

Preflight passed — tell the hooks that the story was taken into work (rules — the
"Extensions" section after Step 4):

```bash
auto-bmad ext fire story-start --story <id> --title "<title>" --epic <N> --level <level> --repo .
```

In Epic mode preflight repeats before each story: the engine leaves the tree clean,
and dirt between stories means someone interfered.

In Story mode drop the `[Story N/M]` prefix. In Epic mode set the current story's task
→ `in_progress`.

## Step 2 — Story run in a subagent

```
[Story N/M] ✅ Preflight → ⏳ Story run → ⬚ Check → ⬚ Sprint sync → ⬚ Report
```

### First — is this a first run or a continuation

The run could break at any point: the spec is written, the code is partly done, the review did not finish.
The engine can continue from the point where it stopped, **but only if it is given the spec path**.
On a free intent it derives the same slug, sees someone else's non-`draft` spec and creates a duplicate
`spec-<id>-2.md`, redoing the whole story. So before each launch:

```bash
auto-bmad spec --story <epic>-<story> --repo .
```

The `route` field in the response says what to do:

| `route` | What happened | What to pass to the subagent |
|---|---|---|
| no spec (code 2, `found: 0`) | first run | intent: `Story <epic>.<story> — <title>` |
| `resume` (`draft`, `ready-for-dev`, `in-progress`, `in-review`) | the work was interrupted | **the spec path** — the engine enters the right step itself |
| `sync-only` (`done`) | the work is done, the tracking lags behind | nothing: do not call the engine, go straight to Step 4 and sync the sprint |
| `ask-human` (`blocked` or an unknown status) | the story is marked as blocked | nothing: the engine would HALT with `story already blocked` — show the human and stop |
| code 2, `found: 2` or more | duplicate specs from earlier runs | do not guess: show the list with statuses and ask which one is real |

Tell the human about a continuation in a line — they must understand why the story does not start
from zero: `Story 3-7: continuing interrupted work (spec in status in-review).`

### Launch

**The subagent calls the engine, not you.** Launch `Agent` with type `auto-bmad:bmad-story-runner`
(plus `model` / `effort` from `agent_args.story-runner`, if the profile returned them) —
inside its own context it calls `Skill: bmad-build-auto`, waits for the HALT, parses the
status, makes the allowed extra review passes and returns a finished report. Verified:
the subagent in this environment can both call skills and spawn its own subagents, so
the engine's review layers and implementer work inside it as normal.

The launch prompt — exactly these fields:

```
Run one story through the BMad engine and return a report by your type's contract.

Story: <epic>.<story> — <title from the queue>
Spec: <path from read_spec — only if route: resume; otherwise omit the line>
Epic: <epic>
Run level: <fast|normal|deep>
Review pass limit: <1|2|3> (the first engine run is pass 1)
Project root: <absolute path>
Language: <run language>

The level profile is already in _bmad/custom/bmad-build-auto.user.toml — do not touch it.
Do not touch sprint-status.yaml: I sync the tracking.
```

The review pass limit comes from the level: `fast` — 1, `normal` — 2, `deep` — 3.

The "Spec" line is present — the subagent passes the engine **the path**, not an intent: the engine enters
the right step itself and finishes what was started, without rewriting what is done.

**Before the launch, remember the story base** — `git rev-parse HEAD`. The check step needs it:
from the `base..story commit` diff it decides which checks to run.

**Exactly one story at a time** (in sequential mode): the engine commits and requires a
clean tree on entry; parallel runs in one tree would fight over the working copy.

`Agent` is asynchronous — end your turn with one line about what you are waiting for, and continue
from the notification.

## How to wait for a subagent

`Agent` in this environment is **asynchronous**: the call returns control at once, and the result
comes as a separate notification, which resumes the run by itself. There is no blocking call
here — neither for you nor for the engine.

1. Launch in **one message** all subagents the step needs.
2. End your turn with one line about what you are waiting for.
3. The notification wakes you up by itself — continue from it.

**Idle calls to "keep the turn" are forbidden.** `echo`, `sleep`, reading the same
file again, `git status` in a loop — a call that checks nothing moves nothing
either: the subagent does not finish faster because of it, and the run goes into a loop of a hundred steps
and burns the context. Polling makes sense only where it reads something the notification does not have.

Read the engine's wording "never end your turn to await a completion notification" as
a ban on leaving work unfinished, not as a ban on ending the turn: in this environment
ending the turn is the normal way to wait.

**Notifications of grandchildren come to you, not to the subagent.** The story-runner spawns the
engine's implementer and reviewers itself, but the harness delivers their completion notifications to the main
session. So the story-runner sometimes returns without a header, with words like "waiting for the implementer" or "waiting for
the reviewers". This is not a failed run:

1. A notification came from an agent you did not launch (`bmad-implementer`, reviewers) —
   forward its result to the story-runner: `SendMessage` to its id, first line "Your
   <agent type> finished, the notification came to me", then the result as is.
2. The story-runner returned without a header and with the word "waiting", and there is no notification — wait
   for it with one end of turn; nothing came — `SendMessage`: "you have no live children,
   check the spec, git log and git status and bring the engine to HALT".
3. `blocked` for "no header" — only if the story-runner, after such a forward, again
   returned without a header and without "waiting".

## Step 3 — Parse the result

The subagent returned two parts: a machine header and a finished report for the human. **Work from the header;
do not read the spec and the diff yourself.**

```
STATUS: done | blocked
SPEC: <path to the spec>
COMMIT: <hash or "none">
FILES: <number>
PASSES: <used> of <limit>
FOLLOWUP_OPEN: no | yes — <risk>
DEFERRED: <number>
QUESTIONS: <number of "Needs attention" items>
```

Part 2 — the report text — keep verbatim; it goes to Step 5 as is.

**No header, or it cannot be read** — the subagent broke down. Take the state from the spec:

```bash
auto-bmad spec --story <epic>-<story> --repo .
```

Code 2 (zero or more than one spec) — treat the story as `blocked` and do not guess. In the report
tell the human in a line that the subagent returned a result outside the contract.

### If `STATUS: blocked`

The engine got stuck; the analysis is in the subagent's report.

- Do not touch `sprint-status.yaml`: the story stays in progress
- **Write the blocker into the open questions file and end the run — with one
  `auto-bmad story-finish` call** (Step 4 describes the input). The story entry has
  `"status": "blocked"`, and its `questions` is the "Where it stopped" and "What can be done"
  blocks from the subagent's report, as is — this is exactly the decision point the file
  exists for. Add `run_end` with `"status": "blocked"`: the run stops here. Run the remembered
  `CLEANUP` commands before this call. The script writes the section, commits the questions
  file (`docs: open questions for epic <N> — story <id> blocked`), fires `story-blocked`
  (the hooks take the text from the section just written) and `run-end`, and records the
  statistics. A refused section (someone else's file) is a line in `warnings`: say it.
- In **Epic** mode — **stop the pipeline** and finish
- Show part 2 of the report as is (the blocked template is in `REPORTS.md`; it ends with the
  `STORY_BLOCKED` marker); in Epic mode
  add the line `Left in the epic: <list of unfinished stories>`

### If `FOLLOWUP_OPEN: yes`

The subagent used the extra review passes itself, within the level limit. "Yes" means
the limit is used up, and the engine still asks for another round. Do not ask for more and do not redo the story:
the risk goes to "Needs attention" — the subagent has already put it there; your job is not to lose it
in the epic report.

On `--fast` the extra pass does not run at all, but do not stay silent about the flag: the level
was chosen by the human, and they must see what it cost.

### If `STATUS: done`

Next — Step 3.5.

## Step 3.5 — Check after a story

```
[Story N/M] ✅ Preflight → ✅ Story run → ⏳ Check → ⬚ Sprint sync → ⬚ Report
```

The engine checked the story with its own commands from the spec. Here go the config checks the
engine does not see: the project's whole test suite, the check on a device and any of your own. They run
on `normal` and `deep`; on `fast` the plan is empty, and the step is skipped. A check found a problem — the engine
fixes it, and the check repeats.

### Plan

```bash
auto-bmad verify plan --story <id> --title "<title>" --base <story base> --commit <COMMIT> \
    --level <level> --repo .
```

- code 2 and empty `verifiers` and `skipped` — nothing to check, go to Step 4;
- `skipped` — the check fits the story, but it cannot run: a needed skill is missing.
  A line to the human and an item in "Needs attention" of the story report: what is not checked
  and how to install it (`install_hint`). The run goes on;
- `verifiers` — checks to run, `fix_limit` — how many fixes are allowed for this story.

### Launch — strictly one at a time

Emulators, ports and the build are shared on the machine, so checks run **sequentially**,
in the order of `verifiers`:

- `kind: command` — `auto-bmad verify run --name <name> --repo .`. The verdict is in the `verdict` field,
  for `problem` the output tail is in `tail`;
- `kind: agent` — an `Agent` subagent of type `auto-bmad:bmad-verifier` (plus `model` / `effort`
  from `agent_args.verifier`, if the profile returned them), the prompt — exactly these fields:

  ```
  Check the story by the instructions and return a verdict by their contract.

  Story: <epic>.<story> — <title>
  Goal: <goal from the queue or "—">
  Base: <story base>
  Commit: <COMMIT>
  Check: <name>
  Instructions: <instructions from the plan>
  Project fields: <fields from the plan as is, JSON — the project's .auto-bmad.toml is already in them>
  Attempt: <1 — first check; N — after N-1 fixes>
  Previous problems: <only from attempt 2 — the PROBLEMS list of the previous verdict>
  Project root: <absolute path>
  Language: <run language>

  How to check:
  <the "How to check" section of the story report as is>
  ```

  Parse the response header (`VERDICT`, `PROBLEMS`, `ARTIFACT`, `FILES_LEFT`) like the Step 3 header.
  No header — treat the verdict as `skipped` with the reason "the check returned outside the contract".
  `FILES_LEFT` is not `none` (for example, a saved Maestro flow) — commit these files in a separate
  commit `test: check scenario for story <id>`, otherwise the next preflight stops.
  `CLEANUP` is not `none` — remember the command (without duplicates) until the end of the run; run it before
  `run-end`.

### Outcome

- all `pass` or `skipped` — Step 4. In the story report — a line `Check: <name> — <verdict>
  [, board: <ARTIFACT>]` for each check;
- a `problem` from a check with `on_fail: note` — an item in "Needs attention", Step 4;
- a `problem` from a check with `on_fail: fix` — **fix**, below.

### Fix

1. Is another fix allowed:

   ```bash
   auto-bmad verify attempt --story <id> --level <level> --base <story base> --repo .
   ```

   `fix_allowed: false` (code 2) — no fixes left, go to "Limit used up".
   `fix` — the number of this fix: it goes into `--pass` below. The call has already counted the fix
   against the limit, even if the engine stops later.
2. Fix tasks go into the spec, and it moves to `in-progress`. In stdin — the problems of all failed
   checks: `PROBLEMS` from agents and, for `kind: command`, the line "tests fail: <command>"
   and the key part of `tail`:

   Write them with `Write` to `.auto-bmad/finish/problems-<id>-<N>.md`, then:

   ```bash
   auto-bmad verify fix-spec --spec <SPEC> --pass <fix number> \
       --problems-file .auto-bmad/finish/problems-<id>-<N>.md --commit-story <id> --repo .
   ```

   The script commits the spec itself (`commit` in the response). Code 1 with `error` — the
   spec is written but not committed: show the error and stop like a story blocker.
3. An `auto-bmad:bmad-story-runner` subagent with the Step 2 prompt and the line `Spec: <SPEC>` — the engine
   enters implementation by the spec path, does only the new tasks, reviews the fix diff
   and commits. Parse the answer by Step 3; `blocked` — like a normal story blocker:
   the spec stays in `in-progress` with the fix tasks, and the next run continues it
   by the `resume` route.
4. A new `COMMIT` from the header — run this step's checks again, `Attempt` +1. **Do not build the plan
   again**: a fix often returns files to the base, and `detect` on the diff would drop exactly the
   failed check. Repeat all checks with the `problem` verdict (take their `fields` and instructions
   from the first plan) and `project-tests`: the fix could break the tests. Do not repeat passed
   checks other than `project-tests`. In the check prompt `Base` stays the story
   base, `Commit` is the new one, "How to check" comes from the first story report (a fix report
   usually has no scenario of its own).

### Limit used up

The last check after the last fix is still `problem`:

- a device check or your own one — the story is still `done`: the work is committed and reviewed.
  In "Needs attention" — an item by the `REPORTS.md` template: what is left, how it shows,
  how many fixes there were, a link to `ARTIFACT`. Step 4;
- `project-tests` without a baseline (Step 0 did not take it) — treat the baseline as green: the project
  tests were not checked before the story, but their failure after the story is still fixed;
- `project-tests` with a green baseline — the tests are broken, and fixing them failed. This is
  `blocked`: open questions, `story-blocked` and the epic stop — by the Step 3 rules.

The outcome of the step goes to the hooks as the `verify-done` event: put it into the
story's `verify` field of the Step 4 input — `story-finish` fires it before the others.
A story that went `blocked` at this step gets the same field in its Step 3 call.

## Step 4 — Sprint sync and open questions

```
[Story N/M] ✅ Preflight → ✅ Story run → ✅ Check → ⏳ Sprint sync → ⬚ Report
```

The engine does not touch the sprint tracking — that is this skill's job. All finishing
steps of a story go in **one** call: the sprint sync, the open questions, the tracking commit,
the hook events and the statistics.

"Needs attention" items live only in the chat, and the human does not read the run in order. So
at the end of **every** story they go into one file per epic — `<questions_file>`.
Building it at the end of the epic is too late: the run may break, and the questions stay unwritten.

First write the input with `Write` to `.auto-bmad/finish/<id>.json`:

```json
{
  "epic": <N>,
  "level": "<level>",
  "stories": [
    {"story": "<id>", "title": "<title>", "spec": "<SPEC>", "commit": "<COMMIT>",
     "status": "done",
     "questions": "<the \"Needs attention\" items as is, by the REPORTS.md template; \"\" when QUESTIONS: 0>",
     "verify": {"status": "<pass|problem|skipped>", "fixes": <number>, "checks": {"<name>": "<verdict>"}}}
  ]
}
```

- `spec` and `commit` — from the Step 3 machine header; `verify` — only when Step 3.5 ran;
- `"questions": ""` — the story closed clean: its section does not appear, and one left from an
  earlier run is removed;
- `"run_end": {"status": "<done|blocked|window>", "done": <closed>, "left": <left>}` — only on the
  call that ends the run (Step 3 blocker; the last story — or see Step 6).

Then:

```bash
auto-bmad story-finish --input .auto-bmad/finish/<id>.json --session ${CLAUDE_SESSION_ID} --repo .
```

The script, in this order: fires `verify-done`; moves the story to `done` in `sprint-status.yaml`
and lifts the epic; writes the story's section in `<questions_file>`; commits both in one commit
(`chore: story <id> → done in sprint tracking`) — the engine left the tree clean and requires it
clean again on the next story; fires `story-done` after the commit, so that a hook reads the files
from disk; commits the files a hook returned; records the statistics.

Read the response:

- `ok: true` (code 0) — go on;
- `failed` is not empty (code 2) — those steps did not go through, the others did. A line to the human
  per failed step with its `detail`. A failed `commit` leaves the tree dirty: show `git status` and
  stop like a blocker; the next preflight would stop anyway. Do not retry the whole call: the
  steps that went through would run twice;
- `messages` — tell the human as is; `links` — keep for the story report as `<name>: <link>`;
- `warnings` — a line to the human each: a hook failed, the questions file was written by a human
  (the items are still in the story report), a section has no closing mark.

Do not edit the questions file by hand: the script replaces only its story's section and keeps
the human's notes between sections.

### Extensions

Hooks are commands from the auto-bmad config that receive run events: a task board,
notifications, anything of your own. Config layers: plugin defaults (`defaults.toml`), personal
`~/.config/auto-bmad/config.toml`, project `.auto-bmad.toml`; the merged config —
`auto-bmad ext config --repo .`. Events: `run-start`, `story-start`, `story-done`,
`story-blocked`, `wave-merged`, `verify-done`, `run-end`.

**`ext fire` never stops the run** and needs no permission. Its exit code is
always `0`; parse the response fields:

- `results` is empty — no hooks for this event, go on silently;
- `results[*].message` — one line to the human as is; the hook decides itself what to say;
- `results[*].error` — one line to the human ("hook <name> failed: <error>") and go on.
  Do not repeat the call and do not fix the hook in the middle of the run;
- `results[*].link` — keep it for the story report as a line `<name>: <link>`;
- `files` is not empty — commit exactly them, as in Step 0 (`story-finish` does it itself);
- `asks` come only with `run-start` — Step 0.

**End of the run — `run-end`, exactly once on any outcome:** the epic is closed, a stop
by the window, a story went to `blocked`, Story mode is finished. Call it before the final report, so that
the hook lines get into it. Before it, run the remembered `CLEANUP` commands from the checks
(Step 3.5), one by one, one per Bash call; one failed — a line into the report, it does not stop the run.

`run-end` goes through `story-finish` too: in the blocker call of Step 3, or as a call with
only `run_end` (no `stories`) — write `.auto-bmad/finish/run-end.json`:

```json
{"epic": <N>, "level": "<level>", "run_end": {"status": "<done|window>", "done": <closed>, "left": <left>}}
```

```bash
auto-bmad story-finish --input .auto-bmad/finish/run-end.json --session ${CLAUDE_SESSION_ID} --repo .
```

`ext.py` also writes every event into the project journal `.auto-bmad/events.jsonl` (excluded
in `.git/info/exclude`, only ids, statuses and time).

## Step 5 — Story report

```
[Story N/M] ✅ Preflight → ✅ Story run → ✅ Check → ✅ Sprint sync → ✅ Report
```

The report is already written by the subagent — show it by the `REPORTS.md` template, adding the line
with the numbers from the header, the link lines the hooks returned in `link`, and the
`STORY_DONE` marker as the last line.
Do not retell it again.

**For the final epic report keep only a summary** of each story: id,
title, spec path, commit hash, number of files and the "Needs attention" items. The human has already read the full
texts — there is no reason to keep them all in context until the end of the epic.

The story statistics (time, tokens by role, review passes and findings; counters only, no
texts) were recorded by `story-finish` at Step 4. A `stats` step that failed there is not a
reason to stop and not a reason to tell the human: statistics are auxiliary. The plugin's
`SessionEnd` hook records the session once more when it ends, so nothing is lost when a call
was denied.

In Epic mode set the current story's task → `completed`.

## Step 6 — Next story (Epic mode ONLY)

**CRITICAL: do not stop after the first story.** The run goes in full autonomy:
there are no pauses between stories; do not ask for permission to continue. Only one thing can cut the queue short
— a `take_next: false` answer from the script in item 2. This is not a pause
and not a question to the human, but the normal end of the run.

1. Remove the finished story from the queue. The queue is empty → the final epic report (below).
2. Ask whether the next story fits into the time window:

```bash
auto-bmad window --stage next-story
```

   - `take_next: true` (including always when there is no window) — **immediately** go back
     to Step 1 with the next story, moving its task to `in_progress`.
   - `take_next: false` — **do not take** the next one: it would be cut off in the middle, and instead of
     done work there would be a dirty tree on which the next
     session would not start either. The reason is in the `reason` field: not enough time to the end of the window,
     the subscription window is used up, or the runner asked for a clean stop (`stop_requested`). Print the "run stopped by the window" report
     by the `REPORTS.md` template, naming the reason in the script's words, and finish the run
     normally, without an error. The tree is already clean at this point: the tracking commit was made
     at Step 4.

   Do not count either the time or the limit yourself and do not dispute the script's decision: only it knows.

The queue is empty → `run-end` through `story-finish` (the "Extensions" section), then the final epic report: set the task `Epic <N>: final report`
→ `in_progress`, then `completed`, and write the report by the `REPORTS.md` template.
**Do not fix** anything from "Needs attention" — that is separate work, and the human decides its size.

By this point the open questions file has been built along the run — there is nothing to rebuild or add
to it. Name it in the report in one line, the last one:
`Open questions of the epic are collected in <questions_file>.` (in the run language)

## Progress bar

✅ done, ⏳ current, ⬚ ahead. The symbols and `→` are fixed; the step labels go in the run language.

- **Story** mode — no prefix: `⏳ Preflight → ⬚ Story run → ...`
- **Epic** mode — with the `[Story N/M]` prefix, where `N` is the ordinal number in the current run,
  `M` is the initial queue length.
  Example: `[Story 3/8] ✅ Preflight → ⏳ Story run → ⬚ Check → ⬚ Sprint sync → ⬚ Report`
