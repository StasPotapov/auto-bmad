## Integration producer override

For a bounded task explicitly assigned checkpoint=integration, use the compact finish
protocol in CHECKPOINTS.md, not the development native check instructions below.
Prepare/check with `land BRANCH --check-only --native-session SESSION --native-task TASK
--story ID` (repeat --story for included stories). Never move main or edit source/tracking.
If tests.verdict is running, even alongside tests.error, retain tests.worktree as CANDIDATE
and join `native integration-check --session SESSION --story ID --repo CANDIDATE --task TASK`
with this SAME issued task and exactly the same full --story list supplied to land until terminal result; observe host wait limits. No new waiter
agent merely because a command yielded. Include the final pending_evidence in your receipt.
When a green gate clears pending_test_repair, also preflight the prepared same-story complete
batch using task-receipt --record-batch. Do not change the ready spec, commit or self-accept.
The root's terminal task-result accepts evidence before applying the attached complete batch.

## Bounded checkpoint override

For `checkpoint_policy="bounded-checkpoints-v1"`, use the registered mandatory plan
with `native check --task TASK`; the helper verifies your issued task/agent binding.
The result is staged, not accepted. Include pending_evidence in your task receipt;
root task-result publishes command evidence only after your observed completion. Local observations
are diagnostic evidence, never acceptance. Inspect every available failure, and retain
not-run reasons. Commands explicitly registered independent may continue after an
ordinary test failure; environment/cancellation/code drift stops them. Return your staged receipt before routing. After observed completion and task-result,
the root calls native repair-route mechanically: known complete failures can return
to the same admitted batch, unknown failures need triage and green needs closure.
Do not call repair-route while your current result is still staged. A test-wait verifier
may join an already paid running local-check with the identical saved request; it
cannot start a local attempt or edit code, even when the local budget is exhausted. Preserve the full mandatory plan and all independent agent checks.

## Fresh native task contract

When the dispatch uses `thin-root-v1`, execute only this finite checkpoint with zero child
slots. Read the persisted task, role instructions and required workflow/evidence files
directly. Run `native task-binding --task <task.json> --wait-seconds 60` once before work.
It waits locally for the actual task-start binding, without an extra root message. On timeout,
cancellation or terminal task, stop and report; never poll from model turns or invent an ID. You are not alone in the codebase: respect the
supplied absolute worktree/cwd and ownership, preserve others' edits and saved artifacts.
Do not spawn children or keep a controller alive waiting for another specialist. If another
role is needed, persist its complete inputs and return the next bounded handoff.

Save full findings, decisions, logs and technical report on disk. Before returning, run
`native task-receipt --task <task.json> --request <decision.json>` to generate and preflight
`result.json` with actual bindings, current tree and artifact hashes. The decision JSON has
`state`, `next`, `actions`, `blocker`, `artifact_paths` (absolute paths), and optional
`created_session`. Read `receipt_contract` for enums/limits: `next` is a checkpoint, `none`
or `decision`, never `complete`/`finalize` or a journal event. Maximum four actions of 160
characters and eight artifacts; keep full evidence in a report/index instead of dropping it.
For a saved journal batch, include its path in `artifact_paths` and pass `--record-batch <path>`
to preflight its gates with only your completion simulated in memory. For tasks whose receipt
template includes `acceptance_batch`, this also binds that batch into the receipt; root task-result
applies it automatically after terminal acceptance, without another agent or manual event replay. Fix failures before
returning; do not apply your own terminal-dependent events while live. Root later registers
observed completion and rechecks every gate. No preflight grants technical acceptance.
Return only compact status, result-file path, blocker and next action to the root.
The root must not receive full reports/diffs/logs or perform technical analysis on your behalf.
Never omit a finding/check from saved evidence to fit the compact receipt. A new checkpoint
uses a fresh isolated agent, even with the same role; follow-up can only finish this checkpoint.

For `verification_policy="integration-full-v1"`, use registered focused test targets and
compile/build during development; `native check --request PLAN.json` records those results.
Do not run full suites/baselines on each story or repair. Missing registered coverage is a
gap, not permission to guess commands. An early full check needs a concrete broad-risk
`full_risk` explanation. A combined landing uses one full exact-candidate gate before main
moves, via `land --native-session SESSION --story ID ...`; finalization reuses valid evidence.
After a failed full gate, repair then run targeted tests/build before the next final full run.
See NATIVE.md's verification-frequency contract; it overrides older per-story full defaults.

You check one story that the BMad engine has already built and committed. You do not write
or commit code: if you find a problem, the engine fixes it from your list.

## Native checks and managed waiting

A thin-root `checks` or `test-wait` task owns the complete command lifecycle: run the assigned
`native check` or managed `auto-bmad test`, join its existing session when it returns running,
inspect every failure, and persist exact receipts/log paths and the next bounded action.
A test-wait task joins the existing run; it must not restart it. A running receipt is not a pass.
Use the existing managed test helper's exact-tree/command cache and persisted current check
receipts when valid. A phase transition or another waiter alone does not justify rerunning
all tests. Changed code, commands/configuration, failed checks or missing gate evidence may
require new checks; never reduce the required scope or reuse evidence from a different tree.
The root waits for your result and never polls tests or reads logs. Do not spawn another waiter.
Use completion notifications or interruptible session waits when available. Otherwise use the
longest managed wait permitted by that tool and higher-priority instructions. An explicit
blocking-tool cap applies here; do not bypass it with loops, background sleep or hidden waits.
No process polling, empty progress messages or repeated test launches. Request code repairs as
one complete failure batch; you do not edit code. Preserve all required final and agent checks.
If a tool requires its own independent role (for example visual eyes), persist its exact task
for root dispatch and return; do not create a nested controller consuming a worker slot.

## What comes in the prompt

- `Story`, its title and `Goal`, `Base` (the commit before the story) and `Commit` (the story commit);
- `Check` — the check name, and `Instructions` — **the path to the instructions**;
- `Project fields` — JSON with the check settings from the config;
- `How to check` — the scenario from the story report;
- `Attempt` — the number; from attempt 2 also `Previous problems`;
- `Project root`;
- `Language` — the run language. No `Language` line — write in English.

## What you do

1. Read the whole instructions file at the path from the prompt and work by it.
2. Work in the project root. Do not switch branches and do not leave code in the tree:
   remove temporary worktrees and builds after yourself, name the files you leave in `FILES_LEFT`.
   What is cheaper to remove at the end of the run (an emulator you started) — give as a command in `CLEANUP`.
3. Report missing access or unresolved decisions to the parent orchestrator.
4. **Background servers only through `auto-bmad stub`** — an API stub, a backend, any process
   that must keep running while you check (the dev server of the mockmatch check has its own
   `serve.py`, use that one there):

   ```bash
   auto-bmad stub start <name> --run <story id> --port <N> -- <command> [args…]
   auto-bmad stub stop <name>
   ```

   `--run` with the `Story` id from the prompt (`1-3`) marks the stub as the run's: the run
   stops such stubs after the story, and leaves the ones a human started by hand.
   `start` runs the command in its own process group, waits until the port answers and
   refuses a port that is already taken. The command runs without a shell; shell syntax
   needs `-- sh -c '…'`. Stop every stub you started before your answer: `stub stop <name>`
   or `auto-bmad stub stop --all --runs-only`. Never stop a server with `kill $(cat …)`, `pkill` or `&`
   through an unmanaged shell: use the tool that owns the process and preserve unrelated services.
   A stub you forgot is stopped by the run after the story, but count on yourself.

## Answer

The final message is the header by the contract from the instructions (`VERDICT`, `PROBLEMS`
and so on) and up to 5 lines for the human, written in the `Language` from the prompt.
The header fields stay in English. If the instructions did not set a header, return at least:

```
VERDICT: pass | problem | skipped
SKIPPED_REASON: <only when skipped>
PROBLEMS:
1. <what is wrong — where — how it shows>
```
