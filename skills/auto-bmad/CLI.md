# CLI backend

Use this mode when the project's resolved `execution.backend` is `cli`. The chat launches and reports;
the shared runtime owns the story queue and the native BMAD controller owns each story's lifecycle.

1. Take the exact story/epic and level from the user's request. An empty argument selects the next unfinished story.
   The read-only `plan` command shows the queue and role profiles. Missing profiles or capabilities are blockers;
   never guess a model ID, replace an adapter or disable a check to make the run succeed.
   The shared `[run].parallel` (`conservative`, `aggressive`, `off`) and `[run].width` (default 3)
   apply to every executor; argument flags override them. Do not force Codex to sequential mode.
   If `wave_plan_required` is true, read **Step P1 — Splitting into groups** of [PARALLEL.md](PARALLEL.md)
   and the epic/story descriptions and relevant project modules. Use those shared dependency rules
   to split the exact returned queue into contiguous waves, each no wider than `parallel_width`.
   Unknown or overlapping scope is a separate wave in conservative mode. This planning happens in
   the surrounding chat, as in the native frontend; do not start extra planning models.
   Save a JSON file outside tracked project files (for example a unique temporary file):

   ```json
   {"base_commit":"<base_commit from plan>","parallel":"conservative","width":3,
    "waves":[{"stories":["1-1","1-2"],"reason":"independent modules"},
             {"stories":["1-3"],"reason":"uses the result of 1-1"}]}
   ```

   Use the resolved mode/width, not these example values. IDs must cover the queue exactly in order.
   Show the actual wave composition in the opening; do not wait for approval to execute an authorized run.
2. When the user asks to run that scope, execute:

   ```text
   python3 <this-skill-directory>/scripts/run.py --repo <absolute-project-root> --arg "<user arguments>" --allow-model
   ```

   Add `--wave-plan <absolute-json-path>` when `wave_plan_required` is true. A stale base, mode,
   width, omitted/duplicated/reordered story or oversized wave is rejected before any execution.
   `--no-parallel`, width 1 and single-story runs need no wave-plan file.

   This may consume the configured models' quota and creates local commits. The user's request to execute
   this story/epic authorizes this run; do not ask again for the same scope. If they asked only for a plan, stop after `plan`.
3. Follow the **CLI chat messages** section of [REPORTS.md](REPORTS.md) for the opening,
   story transitions and final report. Read that section before launching the run. Report actual
   plan/session/result facts; do not narrate guesses about the controller's internal phase.
   Wait for that command. If the shell tool yields a session handle, join it. Do not start another run because
   the first command is still running. The CLI emits `run-started` on stderr before model execution and `run-finished` with the final
   message, report path and actual merge result after completion, with the controller session path; stdout remains the final JSON result.
   The command also emits `story-selected` / `wave-selected` when it admits work and
   `story-finished` / `wave-finished` after the result is saved. Selection means preparation,
   not model execution. A finished event is successful only when `story_completed` is true.
   Join the shell session to receive these events; do not run a separate `status` polling loop.
   For an explicit user status request, cancellation, or one recovery snapshot after losing the shell handle use:

   ```text
   python3 <this-skill-directory>/scripts/run.py status --session <session.json>
   python3 <this-skill-directory>/scripts/run.py cancel --session <session.json>
   python3 <this-skill-directory>/scripts/run.py stop-after --session <session.json> --story <id>
   ```

   A request such as "finish through story X and stop" during a run means `stop-after`, not
   `cancel`. Reuse the session from this run's startup record; do not search logs or guess a PID.
   The receipt confirms the accepted target and lists `already_started_after`: those stories were
   already admitted and will finish too. Tell the human once if that list is nonempty. Unstarted
   waves are split at the requested target; no later work is admitted. Repeating `stop-after` replaces
   the target while control is open. Once stop finalization begins, changes are explicitly refused;
   an accepted target is never silently ignored. Status shows the saved target immediately. Old sessions without `control_version: 1`
   refuse this command; report that limitation, never simulate it with polling or kill a process.

4. Report `run_completed`, completed and remaining stories, test/check outcomes, concrete questions,
   and the worktree/branch. A failed role, `needs_attention`, `window`, or partial queue is not success.
   `execution_status: stopped` is an intentional clean stop, not a completed epic: show `stop_after`,
   `stop_target_reached`, completed/remaining stories and normal token accounting. The CLI exits 0
   for this clean stop while keeping `run_completed: false` for unfinished epics.
   Include any returned `statistics.error`; accounting failure must not be presented as zero usage.
   Always include token accounting in the final report, including stopped or failed runs; do not wait
   for a token question. Use `<plugin-root>/bin/auto-bmad stats show --repo <project> --epic <N> --calls --json`.
   Select only rows belonging to this run: match `queue_id` to the returned queue session directory's
   name, or `session` to `cli:<session-directory-name>` for a direct story session. An epic filter alone
   includes older runs; `--last 1` can select a different concurrent run. Do not mix them into this run's totals.
   Resolve the plugin root from this source package. CLI usage
   is recorded automatically, including the story controller and retries; the surrounding chat is excluded.
   Hook questions are saved to the epic questions file after the queue; never ask live or invent an answer.
   Use the plan's language, or the user's language if unset. Keep the report short.

## Autonomous questions

Do not interrupt an authorized run for routine implementation choices or non-blocking editorial questions.
Use authoritative requirements and existing conventions. If exact source wording is mandatory, keep it and
record a disputed example in the triage log, Auto Run Result and returned `questions`; finish the other fixes,
reviews, tests and stories. Copy-review requests remain open questions; they do not interrupt the queue or opt-in landing.
Never label that editorial disagreement `intent_gap` or roll back the implementation for it.

Repair budgets are independent per story run on every level: `[repair_limits]` defaults to
`spec=2`, `review=5`, `tests=10`, `no_progress=3`. Follow-up passes do not reset them.
`repair {"reason":"code_fix"}` spends review budget; `rollback {"reason":"bad_spec"}` spends
spec budget. For failed registered commands, use `repair {"reason":"test_failure",
"failure_id":"<host-issued id>"}` before editing; this spends tests only. Rerun the same
check before another repair. Three attempts without a pass or a strict reduction of
known failing test IDs block the story. Changed error text/code alone proves no progress.
Unknown output formats require a pass or host-verified exact baseline equivalence to reset
the streak. A verified baseline match closes the regression; arbitrary skips do not. Recognized infrastructure
failures are blockers rather than code repairs and refund a pending test attempt.

Test fixes iterate in place without spec rewrites or independent review on every small
attempt. Once stable, all active review layers on the final whole-story diff and full
configured checks are mandatory. Old reviews/checkpoints cannot finish changed code.
Post-story command failures enter this same loop; agent-verifier findings use review
budget. No spec fix-task commit is created just to repair tests. `[verify_limits]` is
deprecated and ignored. Zero disables a repair category; no_progress must be positive.
Config changes require a new prepared run; never silently reset an active budget.

Genuine blockers remain: no safe implementation within mandatory requirements, missing access, or exhausted repair limits.
Never waive acceptance criteria, security or permission boundaries to continue. Return `blocked` with the concrete question;
the runtime writes it to `epic-<N>-open-questions.md` before ending the run, without marking the story done.
In waves the shared run worktree collects blocked questions without merging the failed story's code.
If cleanup, frozen configuration or file ownership prevents finalization, report `needs_attention`, retain the question in
the saved result and show the finalization error; do not claim the epic questions file was updated.

The CLI creates a unique `codex/auto-bmad/...` branch and an isolated worktree from the source's exact clean HEAD.
The source branch stays unchanged during implementation; opt-in epic landing happens after verification. Each wave's stories run concurrently in separate worktrees with
fresh controllers. Waves execute in order; a single-story wave runs directly in the isolated run tree.
Successful branches merge in queue order into the isolated run branch, never into the source branch.
Project tests run against the merged wave before one shared sprint/questions finalization. A failed
story or merge preserves its worktree; successful siblings may still integrate, then the epic stops.
Code conflicts are reported for human resolution, not guessed. Test/device checks share a resource
lock across linked CLI worktrees. All run/story worktrees are preserved. Time-window checks happen between waves.
`--timeout` is an opt-in total hard limit; never invent a deadline for the user. Without it, queue/story duration is unlimited.
Model profile `timeout` is an inactivity threshold; supervised child work pauses the parent's idle clock.
Inactivity first records `suspected_stall`; another `min(120, timeout)` seconds without progress or supervised child work stops the attempt as `stalled` with edits preserved.
Do not use CPU probes. This is a bounded wait for observable progress, not proof that every quiet operation has deadlocked.
With `[execution] merge_policy = "auto-main"`, completed epics automatically merge into local `main`.
The main branch must already be checked out in a local worktree. If it advanced, the runtime prepares
a merge in the isolated run tree and repeats project tests when product files changed. Conflicts,
dirty worktrees, failed or missing checks preserve work and return a concrete failure report.
Editorial questions do not gate merging. Story-only runs and `manual` policy do not merge.
Push, worktree deletion and crash resume remain outside this run. `--parallel-fast`, `--width` and `--no-parallel` are supported;
`--no-worktree` remains unsupported.

The runtime launches roles through adapters and configured profiles. Codex execution has a live single-story
validation. Kimi and Claude CLI adapters currently fail closed until their permission/result contracts are
validated; native Claude Code keeps the separate legacy path. Agent checks run through the configured verifier profile, retaining mockmatch/adbm settings and their
pass/problem/skipped contracts. Missing skills or external services are reported explicitly; never disable
checks to make a run appear successful. Conditional review layers remain unsupported. Report these capability limits without switching to manual implementation.

This skill must ship with the plugin's `scripts/` and `bin/`; installing only a copied `SKILL.md` is insufficient.
For local development, link the entire skill folder to the source checkout. Do not edit installed plugin caches.

## Tests and model permissions

Model roles retain their configured sandbox. A parent's permission grant does not change that sandbox.
`auto-bmad test --session <session> --repo <worktree>` delegates the registered `project-tests` check
to the host controller; `--name` selects another registered command check. An exact registered
`--command` is routed the same way. Names, commands and budgets are frozen from the validated config.
The bridge accepts check names only, not arbitrary shell commands, and refuses read-only reviewer leases.
Host checks use the runner's already-granted environment/permissions, immutable result cache and shared locks.
Outside the verifier phase, an unregistered partial `--command` still runs within the caller's sandbox.
Verifiers must use registered full/development checks: an unregistered command is refused before starting
a worker, because the verifier already owns the shared resource lock. If a sandboxed partial command
hits Docker, local-port or browser-cache restrictions, run the registered full check before deciding the
story is blocked. Never disable checks or broaden model permissions automatically to make them pass.

With `[project_tests.scopes]`, `project-tests` selects components from the complete actual diff,
including committed, uncommitted, new and deleted files. Unknown/shared product paths run the
configured fallback once, or all components without a fallback; documentation ignores select none. Scopes, commands and dependency paths
are project-specific and shared by executors; setup proposes and discusses them with the user.
The pre-story baseline is deferred until affected paths are known, then runs only those components
against the pinned original commit in a separate preserved worktree. It never runs an unrelated
backend just to establish a frontend baseline. Component results reuse the host cache when their
own inputs and shared inputs have not changed. Merged waves select the union of changed components.
Report the selected component names and reused results in the short check summary.

In scoped CLI sessions, unregistered partial commands are refused before execution: use
`--name project-tests/<component>` or the automatic `project-tests` alias. Register any extra approved
checks in configuration rather than running custom builds inside the model sandbox. `--rerun`
explicitly refreshes host test results after an environment repair. Native/non-session commands
use the same strategy with `auto-bmad test --base <pre-story-commit> --repo <worktree>`.
Outside a controller session the entire component plan continues in a detached worker:
`--wait` bounds the caller wait and repeating the command joins it. `--rerun` refreshes
stale baseline and command results; the normal 120-second recent-result window still applies.

## Completion report and notifications

Every saved queue writes `report.md` next to `result.json`, with failures, deferred questions and a compact
token table by role, model and effort. `merge.status` distinguishes `merged`, `not_merged` and `not_requested`.
`run_completed` is false when requested automatic landing fails. No question is answered implicitly.
Existing `run-end` hooks still run before the final tree gate. To notify about the actual final outcome,
configure a notification hook for `run-result`; its `data` includes `message`, `merge`, `session` and `report_file`.
It uses the command frozen at startup and must not edit files or request an answer. Delivery errors are
retained in the report; no messenger or recipient is configured automatically.
