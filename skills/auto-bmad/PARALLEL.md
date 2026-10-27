# Parallel mode — epic stories in separate worktrees

Read it in Epic mode always, except with `--no-parallel`: parallel here is the default
behaviour, not an option. `--parallel-fast` changes only how stories are picked for a wave
(aggressive instead of conservative), `--width N` — the wave size.

In Story mode do not read it at all: there is nothing to parallelize when there is one story.

## What changes compared with a sequential run

| | Sequential | Parallel |
|---|---|---|
| Where a story runs | subagent, shared working tree | subagent + **its own git worktree and its own branch** |
| How many stories at once | one | up to `N` (3 by default) |
| Where the engine commits | the current branch | `auto-bmad/<story-id>` inside the worktree |
| Who combines the result | nobody, everything is already in the branch | the orchestrator merges the group's branches one by one |
| `sprint-status.yaml` sync | after each story | after the whole group is merged, in one commit |
| Open questions file | after each story | after the wave is merged, in the same commit |
| Tests | the engine, by the spec's `## Verification` | plus a baseline before the first wave and a run of the project tests after the worktrees are removed |

Worktrees, not just branches: branches in one tree need `git checkout` between stories,
and parallel agents would fight for the working copy. A worktree gives each one its own directory
and its own index — they physically do not get in each other's way.

## Step P0 — Parallel preflight

```bash
auto-bmad preflight --repo . --parallel --level <level>
```

On top of the usual checks the script looks at what matters only here: whether the engine skill
and `render_skill.py` are under git (otherwise they will not be in a new worktree and the engine
will not start there; if not — `engine_untracked` holds the reason: an ignore rule `ignored_by`
with file, line and pattern, or simply not committed, and the fix `fix`), whether worktrees are left from a previous run, and whether `.claude/worktrees/`
is closed in `.git/info/exclude` (`git_excluded` in the answer) — without this entry the very first worktree
makes the tree dirty, and the next preflight stops on it.

- `blocking` is not empty — stop, as in the usual preflight.
- `parallel_ready: false` — parallel is impossible: tell the human why in one line
  and go with a sequential run by Steps 1–6. This is not a stop. If the reason is the engine
  outside git (`engine_untracked` is not empty): name the fix from the `fix` field to the human and repeat
  it in "Needs attention" of the final report by the template from `REPORTS.md`: the risk is
  that the stories go one by one; the option and the recommendation — `fix`. Do not edit `.gitignore` yourself and do not commit skills in the middle of
  the run — that is the human's decision, not part of the epic.
- `stale_worktrees` is not empty — show them to the human and ask whether to remove them
  (`auto-bmad worktree remove --path <path from stale_worktrees> --repo .`). Exactly
  `--path`: a directory created by isolation has its own name, and the form `remove <story-id>`
  fails on it. Do not delete someone's work yourself.
- `branch` from the answer is the base branch: merges go into it; worktrees branch from its HEAD.
- `test_command` — what checks the result of a wave. The script finds it in advance, before the first wave,
  so that there is no guessing after the merge. If it is empty, there is nothing to check with; tell the human so.
- The warning about `.claude/` is important: see "Test baseline" right below.

### Test baseline — before the first wave

The worktree directory lies **inside** the working tree: the harness puts it in the repository's
`.claude/worktrees/` — the same place as `worktree.py add`. Preflight
closes this path in `.git/info/exclude`, but that saves only git: guard tests
that walk the repository files (looking for duplicates, hardcoded values, forgotten TODOs) walk the file
system, not the index — they see a second copy of the code in the directory and fail not because of
your merge. Preflight warns about this when `.claude/` is not excluded anywhere in the
project's configs.

So before the first wave, if `test_command` is found, run it once on a clean
tree and remember the result. If Step 0 already took a baseline (`auto-bmad verify baseline`),
you do not need it a second time — its result is the baseline of the waves:

```bash
<test_command>
```

- Green baseline — from now on any failure after a wave is yours; deal with it.
- Red baseline — the tests were failing **before** the run: tell the human in a line,
  and from then on compare with this state, not with green. Otherwise you would claim someone
  else's breakage as yours and stop the epic for nothing.

## Step P1 — Splitting into groups

Read `epics.md` (the section of the needed epic) and split `pending_stories` into **waves**:
inside a wave stories run in parallel; waves run strictly one after another.

The order of stories inside an epic must not change: story `1-5` cannot go into a wave earlier
than `1-3` if that one is not done yet. A wave is always a continuous piece of the queue from its start.

**Where the story description comes from.** `epics.md` may have no story headings at all —
in some projects stories live only as slugs in `sprint-status.yaml`, and `epics.md` describes
the epic as a whole. Then the material for splitting is the story slug and the epic text, and that is little:
tell the human in a line that the project has no story descriptions and the split is made by slugs,
and at the conservative level, with this little data, keep waves short.

**What separates stories into different waves** (any sign is enough):

- an explicit dependency in the text: "after story X", "uses what was done in X", "depends on";
- a shared file or module named in the descriptions of both stories;
- one creates an entity (model, table, endpoint, screen), the other uses it;
- both touch a shared assembly point: config, router, DI container, migrations, DB schema;
- the story is described so that the scope of changes is unclear.

**Conservative (default).** A wave gets only stories
that have none of the signs above. If in doubt, separate them into waves: the cost of a mistake
here is asymmetric — an extra wave costs time, a wrong parallel costs conflict resolution
and out-of-sync interfaces.

**Aggressive (`--parallel-fast`).** A wave gets everything except an explicit dependency
from the first item and a shared assembly point. Overlapping files and "unclear" do not block
parallel — conflicts are resolved at merge. The human chose the level; do not revise
that decision, but do not hide the consequences either: in the epic report say how many merges
needed resolution.

**Wave size** — no more than `N` (3 by default; the human may have given another number
in the argument). If a wave has more stories, cut it into several waves in queue order.

A wave of one story is an ordinary sequential run: do not create a worktree for it,
run it by Steps 1–6; there is nothing to merge.

**Show the plan to the human as one table** before the first launch, and do not wait for confirmation.
This is the run table from Step 0 of `SKILL.md` for the parallel mode: titles
and goals from `stories[*].title` / `goal` of the `plan_run.py` answer; an empty `goal` — `—`.
Write the table in the run language; the example is in English:

```
Epic 1: Account tracking — 6 stories, 3 waves (conservative, up to 3 at once)

| Wave | Story | What is done | Why in this wave |
|---|---|---|---|
| 1 | 1-2 · Account model | store accounts and their balance | |
| 1 | 1-3 · Statement import | load a bank statement from CSV | |
| 1 | 1-5 · Settings screen | choose the default currency | |
| 2 | 1-4 · Account list | see all accounts on the main screen | uses the model from 1-2 |
| 3 | 1-6 · Transfers | transfer between accounts | shared DI module with 1-4 |
| 3 | 1-7 · Export | export transactions to CSV | |
```

Write the reason for the wave split in the last column as one short phrase, and only
for stories that moved out of an earlier wave — the human needs it to catch
your mistake before it costs a run.

## Step P2 — Launching a wave

**The first line of the step is the machine marker of the wave taken into work**, verbatim
and on its own line:

```
WORK_START: wave <number> (<story ids, comma-separated>)
```

An external runner that watches the stream reads it: by it the runner sees what was taken into work
after the end of the time window. The `[Story N/M]` progress bar is not printed here, and without this
line a broken window goes unnoticed until the run ends.

Right after it — **a table of what is launched at once**. There is no progress bar in parallel,
and without the table the human does not see which stories are running now; print it at the start of every
wave, not only the first:

```
Wave 1 of 3 — launched in parallel: 3

| Story | What is done | Branch |
|---|---|---|
| 1-2 · Account model | store accounts and their balance | auto-bmad/1-2 |
| 1-3 · Statement import | load a bank statement from CSV | auto-bmad/1-3 |
| 1-5 · Settings screen | choose the default currency | auto-bmad/1-5 |
```

Next — the `story-start` event to the hooks, one call per story of the wave (rules — the
"Extensions" section in `SKILL.md`; this step does not stop the run):

```bash
auto-bmad ext fire story-start --story <id> --title "<title>" --epic <N> --level <level> --repo .
```

**The subagent's isolation creates the worktree, not you.** Launch every agent of the wave
with `isolation: "worktree"` — the harness creates a separate directory for it (in the repository's
`.claude/worktrees/`) and pins the working directory inside it.

This is the only way that works, and the directory cannot be prepared in advance — checked
on both paths:

- an agent **without isolation** gets a refusal from `EnterWorktree`: switching is allowed only
  to one whose working directory is already inside a worktree, and its directory is the repository root;
- an agent **with isolation** gets success from `EnterWorktree`, but the very first command hits
  Bash: "Refusing to run it there" — the sandbox is pinned to the directory the harness gave it.

So do not call `worktree.py add` in the main thread: there is nobody to give its directory to.

Remember the base before the launch — the agents set their branches from it:

```bash
git rev-parse HEAD
```

Launch **all** subagents of the wave in ONE message, otherwise they run one after another.
The type is the same, `auto-bmad:bmad-story-runner`, with the same `agent_args` parameters; four lines are added to the prompt from Step 2
(it already has `Language:`):

```
Isolation: you work in your own git worktree created at launch.
Branch: auto-bmad/<story-id>
Base: <sha from git rev-parse HEAD>
Main repository: <absolute path to the main tree>
```

What the agent does with this itself (described in its instructions): it checks that it really
is in a worktree and not in the main tree; sets the branch to the right base
(`git checkout -B auto-bmad/<story-id> <base>`) — so it does not matter what the harness
branched the directory from; copies from the main repository the level profile that a fresh
worktree does not have; and returns `BRANCH` and `WORKTREE` in the header.

**If the agent returned `blocked` with a reason about isolation**, it did not get a worktree.
Tell the human and finish the wave sequentially, by Steps 1–6: this is no reason to drop the epic.
A frequent cause shows in preflight: `has_origin: false` with `worktree_base_ref: fresh`.

While the wave runs, **do nothing in the main tree**: any commit of yours moves the base
the story branches came from and turns a clean merge into a conflicting one.

## Step P3 — Collecting the wave

Each agent returns the header from Step 3 plus two fields:

```
BRANCH: auto-bmad/<story-id>
WORKTREE: <path>
```

Parse them as in the sequential mode, with one correction: **the spec fallback
here looks for it in the worktree**, not in the main tree. The spec is written and committed by the engine
inside the story branch and reaches the main tree only after the merge, so with a broken
header call the script with the path from the `WORKTREE` field:

```bash
auto-bmad spec --story <id> --repo <WORKTREE>
```

Calling it with `--repo .` before the merge means you are sure not to find the spec and declare
`blocked` a story that is in fact done.

`STATUS: blocked` of one story
**does not cancel the merge of the others**: they are done and checked; their work is not lost.
Do not merge the blocked story's branch and do not delete its worktree — unfinished work is there;
after a wave with a block the epic stops by the general rule.

## Step P4 — Merge

Merge one at a time, in story queue order, into the base branch from P0:

```bash
git merge --no-ff auto-bmad/<story-id> -m "merge: story <story-id> — <title>"
```

**You resolve a conflict yourself.** Look at `git status` and the conflicting places, resolve them
by the meaning of both stories and finish the merge. The resolution is code that no engine
reviewer has seen: keep intervention minimal (take both sides where they
complement each other; do not rewrite logic along the way) and always name it in the story
report as a separate "Needs attention" item.

**If you are not sure you understood the conflict, do not guess.** Stop the merge (`git merge --abort`),
describe it to the human right in the session: which stories collided, in which file, what each
of them does there and what exactly you lack to decide. Wait for the answer and finish the
merge together with the human. The other stories of the wave keep merging meanwhile — do not hold them
for one disputed place.

**Merged — remove that story's worktree and branch at once**, do not leave it to the end of the wave:
while the directory lives, a second copy of the code lies in the working tree. The path is from the header's `WORKTREE` field:

```bash
auto-bmad worktree remove --path <WORKTREE> --repo .
```

Not merged (conflict postponed, story `blocked`) — keep both the worktree and the branch and name
them to the human in the report: their work is there; it must not be deleted.

## Step P5 — Cleanup and tests after the wave

The stories were checked in isolation; nobody checked them together, and the merge could have combined
incompatible pieces. But before you run anything, remove the code copies from the tree.

### 1. Cleanup is required and goes first

```bash
auto-bmad worktree prune --repo .
```

The script removes the worktrees of all stories whose branches are already merged into HEAD, and does not touch those
where the work is not combined. Look at the `clean` field:

- `clean: true` — the tree is clean; the tests measure exactly what you merged;
- `clean: false` — look at what exactly caused it; the causes differ:
  - **`unmerged` is not empty** — the directories stayed legitimately (a conflicting merge, a `blocked` story).
    Tests that walk the repository files will catch a second copy of the code in them. Run them
    anyway, but **treat the result as unreliable**: tell the human which directories stayed,
    and do not stop the epic on such a failure until you are sure the copies are not the cause.
  - **`failed` is not empty** (exit code 1) — the cleanup broke: `git worktree remove` refused,
    the text is in `result.error`. A frequent cause is uncommitted or untracked files
    the engine left in the worktree. This is not "uncombined work": show the error to the human
    and deal with it, rather than blaming a future test failure on code copies.

### 2. Tests

The command is known from preflight (`test_command`). Run it and compare with the baseline:

- **Passed** — go on; in the wave report one line: what you ran and what passed.
- **Failed, and the baseline was green** — **stop the epic**. Do not fix it yourself: a failure after a merge
  means the stories are incompatible in substance, and that is a discussion with the human, not an edit
  on the go. Show the command, the output (only the failed tests, not the whole log), which stories
  are in the wave and what is already merged. Do not revert the merge without the human's word.
- **Failed the same way as on the baseline** — this is not your breakage: say so in a line and go on.
- **No command** — write so in one line: "The wave's stories are not checked together:
  no test command found in the project." Do not invent a command and do not try at random.

## Step P5.5 — Checks of the wave's stories

The whole project test suite already passed at Step P5 — do not repeat `project-tests` here.
The other checks of Step 3.5 of `SKILL.md` (on a device and your own) run for each merged
story of the wave, **strictly one at a time**, in the main tree: emulators and the build are shared.

For each story — everything by Step 3.5, one `auto-bmad` call per Bash call (no `for` loop
over the stories, no pipe into `python3 -c`): `verify plan` with its base (the sha from the `Base` line
of the wave launch) and its commit, the launch, the outcome. `--base` is the same wave base, `--commit` is
the story's merge commit (`git log --merges -1 --format=%H --grep "story <id>"`).

Fixes also go by Step 3.5, but sequentially in the main tree, without a worktree:
the tree is clean after the merge, and the engine's fix run commits straight into the base branch. After
a fix, run the project tests again (`auto-bmad verify run --name project-tests --repo .`):
a fix of one story could break a neighbour.

## Step P6 — Sprint sync, open questions and the next wave

1. **All finishing steps of the wave go in one `auto-bmad story-finish` call** — the input and
   the response are in Step 4 of `SKILL.md`. Write `.auto-bmad/finish/wave-<number>.json` with
   `Write`: one entry in `stories` per story of the wave — merged ones with `"status": "done"`,
   stopped ones with `"status": "blocked"` — plus `"wave": <number>`:

   ```json
   {"epic": <N>, "level": "<level>", "wave": <number>,
    "stories": [{"story": "<id>", "title": "<title>", "spec": "<SPEC>", "commit": "<COMMIT>",
                 "status": "done", "questions": "<items as is or \"\">", "verify": {…}},
                {"story": "<id>", "status": "blocked", "questions": "<Where it stopped + What can be done>"}]}
   ```

   ```bash
   auto-bmad story-finish --input .auto-bmad/finish/wave-<number>.json --session ${CLAUDE_SESSION_ID} --repo .
   ```

   The script moves all merged stories to `done` in one sync and raises the epic status, writes
   each story's questions section, makes one commit for the wave
   (`chore: stories <id>, <id> → done in sprint tracking`), then fires `story-done` /
   `story-blocked` per story and one `wave-merged`, and records the statistics.

2. Do not call it before the merge: until then a story's spec lies in its branch, and `spec` must
   point to a file in the main tree. The merge conflict resolution must be among the
   story's items — this is where it goes into the file. `verify` of a story comes from Step P5.5.

3. The wave stopped the epic (a blocked story, tests failed after the merge) — add
   `"run_end": {"status": "blocked", …}` to the same input after the `CLEANUP` commands.

4. Show the reports of the wave's stories one after another, each by the template from `REPORTS.md`,
   adding a line about the merge if it was not clean. Each report ends with its machine
   marker, verbatim and on its own line: `STORY_DONE: <id> commit=<sha> files=<n>` for a merged
   story, `STORY_BLOCKED: <id>` for a stopped one.
5. The tree is clean again; the base has moved. Ask whether the next wave fits
   into the rest of the run — by time and by the subscription limit:

```bash
auto-bmad window --stage next-wave
```

   - `take_next: true` (including always when there is no window) — to the next wave
     from Step P2.
   - `take_next: false` — **do not start** the wave: it ends with a merge, and a merge dropped
     in the middle leaves worktrees and a dirty tree — even the next run
     does not start on it. The reason is in the `reason` field: the window time ran out or
     the subscription window is used up. Print the "run stopped by the window" report
     by the template from `REPORTS.md`, naming the reason in the script's words and how many stories
     are left, and finish.

   **Inside a wave neither the window nor the limit is checked.** A wave is atomic, just like
   a story: finish a started one through the merge and the sync. So the wave is the place
   where the subscription limit can go far past its threshold — it brakes at the wave boundary.

When the waves are over — the final epic report from Step 6, plus two lines at the start:
how many waves there were and how many merges needed resolution.

## Resuming after a break

If a parallel run broke off, the work is not lost, but it does not lie where the
normal resume looks for it: the spec and commits stayed **in the branch `auto-bmad/<story-id>`**,
and the main tree does not have them. So `read_spec.py --repo .` for such a story returns
"no spec", and Step 2 starts it from scratch, although it is done.

Preflight gives the sign of a break: `stale_worktrees` is not empty. Deal with this **before** planning
the waves, together with the human, one story at a time:

1. Look at what is in the branch: `auto-bmad worktree list --repo .` gives each worktree's last
   three commits (`log`) and its uncommitted files (`dirty`); then the spec status
   `auto-bmad spec --story <id> --repo <worktree>`.
2. The spec is `done` and there is a commit — the work is finished: merge the branch by the rules of Step P4,
   sync the tracking and remove the worktree. Do not put this story into the queue.

   You have no subagent report for it, so there are no items for the open questions file either:
   do not make them up from the spec; tell the human in a line that for this story the questions remain
   only in its spec, and give the path to it.
3. The spec is in an intermediate status (`draft`, `in-progress`, `in-review`) — the work
   is not finished: show it to the human and ask whether to finish it or start again.

   **To finish it, give the branch, not the directory.** The old worktree cannot be given to an agent
   (see Step P2), and it is not needed: all the work lies in the branch `auto-bmad/<story-id>`.

   First check that everything is committed: uncommitted work is lost here. The `dirty`
   field of `auto-bmad worktree list --repo .` lists it. Then remove the directory, freeing
   the branch for a new agent:

   ```bash
   auto-bmad worktree remove --path <worktree> --keep-branch --repo .
   ```

   If `dirty` is not empty — or it is `null` with an `error`, so the state is unknown — show
   it to the human and ask before removing: this work
   exists nowhere else. Then launch an ordinary wave agent with `isolation: "worktree"`,
   but in the **`Base` line pass the branch name** `auto-bmad/<story-id>`, not a sha: the agent
   switches to it with `git checkout` and continues with the ready spec and commits.
4. The branch is empty, no commits — remove the worktree (`worktree.py remove --path <worktree>
   --repo .`; the branch goes with it) and queue the story as an ordinary one.

Do not delete a branch with commits yourself: the human has not seen this work.

## Emergency cleanup

If the run broke off and worktrees are left, do not drop them silently. Show the human the list
(`git worktree list`) and the commands that clean it:

```bash
auto-bmad worktree list --repo .
auto-bmad worktree remove --path <path> --repo . [--force]
```

`list` shows both directories created by the script and those created by isolation: they are recognized
by a path inside `.claude/worktrees/` or by the branch `auto-bmad/<story-id>`. A branch alone
is not enough — the agent sets it already inside the worktree, and a directory where the run broke off before
this step has the harness's branch. The main tree never gets into the list.

`--force` also removes uncommitted work — do not give it without the human's word.

Delete only what was merged successfully. Everything else is work the human
has not seen yet.
