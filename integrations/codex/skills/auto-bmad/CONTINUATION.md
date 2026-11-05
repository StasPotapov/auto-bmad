# Host-owned continuation for unattended runs

This is an optional Codex desktop capability, not a Python scheduler. When the user
requests an unattended epic, automatic technical recovery, or completion without manual
continuation, register a native **heartbeat on the original main chat** before dispatch.
A normal invocation still runs the entire requested scope in its current turn; it must
not finish after one story. Do not create scheduled work for a planning-only request.
If the user has not authorized recurring continuation, do not silently add it.

Use the actual app automation tool and its live schema. No CLI model, private app database,
launchd job, self-sent message loop, new chat, or standalone cron job is a substitute.
If the host lacks heartbeat support, state that recovery after loss of the main turn is
unavailable; keep working in the active turn. Never claim a saved journal can wake a model.

## Register once

1. Resolve the actual root chat UUID, durable native session and original pinned runtime.
   Keep the run's runtime and topology even after updating the installed skill. A newer
   helper may manage the separate host continuation sidecar for an older session; its
   workflow/check/resume commands still run from the original package.
2. Inspect `host-continuation.json` beside the session and the host's existing automations.
   Match the exact session and target chat. Reuse/update the same heartbeat, never duplicate
   it or overwrite an unrelated automation. A registration with an uncertain response must
   be reconciled through the host before retrying creation.
3. Use `kind: heartbeat`, target the original chat, and start with a five-minute interval
   when supported. Do not override model, effort, permissions or notification settings.
   The host must skip a busy chat; verify that capability instead of periodically sending
   prompts to an active turn. Discover the live schema before choosing schedule fields.
4. Write the prompt in the user's language using the contract below. After actual successful
   registration, save its returned automation ID with:
   `native host-bind --session <session> --request <private-json>`.
   JSON: `{"thread_id":"<actual UUID>","automation_id":"<actual ID>"}`.
   Save the helper package path and automation ID in the heartbeat prompt too. If binding
   fails, pause the newly created heartbeat and report the failure; do not leave it orphaned.

The helper stores only `host-continuation.json`, under the same journal lock. It neither
starts a model nor changes story state. Creation/pausing of a heartbeat is a host operation;
the sidecar alone does not install, schedule, stop, or prove a live automation.

## Heartbeat prompt contract

Include the exact session, root chat UUID, original runtime, guard-helper path and scope.
Instruct each wakeup to:

- Inspect the latest relevant **preceding** turn through host tools, excluding the current
  heartbeat. Check intervening user instructions and outstanding approvals/questions.
  A heartbeat's own prompt is never fresh user authorization. Consume a stop before any
  recovery. Do not infer a failure from elapsed time, stale journal status, or an empty wait.
- If that turn or a later user instruction cancelled/interrupted/paused work, pause this
  automation and persist the observed stop through `host-recover` before ending this
  wakeup. Inspect real child liveness, stop/join remaining agents and record their terminal
  states; then use the original journal's `cancel` command for cancellation. Never cancel
  the journal while children are still active. Treat host `interrupted`, including `aborted by user`, as a stop
  even when the person may not have clicked Stop. Do not relabel it as a technical failure.
  Unknown cause, authentication/access/budget errors and required user decisions also stop.
  Record these through `host-recover` too (`unknown`, `waiting-user`, `waiting-approval`,
  or `failed` with its actual non-recoverable cause); preserve the concrete blocker.
  Pending approvals/questions remain for the user, not a fabricated cancellation.
  For an explicit user stop instruction, add `stop_requested: true` with the actual
  observed turn status; do not invent an `interrupted` host event.
- For a confirmed terminal technical failure (`transport` or `host-exit`) or a premature
  completed response with unfinished authorized work and no unanswered question, save a
  compact request with actual `thread_id`, `automation_id`, `turn_id`, `turn_status` and
  `cause`. Run `native host-recover --session <session> --request <private-json>` using the
  guard helper. Normalize host states to `active`, `completed`, `failed`, `interrupted`,
  `waiting-user`, `waiting-approval`, or `unknown`. Do not invent IDs or a recoverable cause.
- The helper returns `continue`, `wait`, `already-claimed`, or `stop`. Only `continue`
  authorizes the recovery path within the user's original scope. `wait`/`already-claimed`
  do not launch duplicate work. `stop` or a helper error requires pausing the automation;
  report a new blocker once. A previously disarmed binding never rearms itself.
- On `continue`, inspect only compact `summary` and actual native agent liveness in the
  root. Dispatch a fresh finite recovery specialist to validate the original session with
  its original `resume` helper, inspect saved evidence/worktree/command liveness and return
  the next bounded task. For a new thin-root session, a finite verifier joins detached tests
  using the same `check` command; a `running` receipt is not a pass and must not trigger a
  new test run. Legacy sessions retain their original runtime/policy; do not rewrite them. Preserve worktrees, evidence and all counters.
  Never replace an active writer, reimplement a completed story, or skip a gate.
  Bind statistics to the new actual turn IDs when available. Continue all remaining
  dependency waves in this turn; the heartbeat is a safety net, not a per-story queue.
- Keep quiet when nothing actionable changed. Notify only on a meaningful change,
  completion, failure or required user action. On completion, cancellation, a real blocker,
  exhausted retries or revoked authorization, pause this exact heartbeat through the host.
  Inspect its current full fields first and preserve unrelated fields on the update.

Host recovery has a separate bounded budget, using the saved `technical_limit`. Repeated
delivery of the same terminal turn is claimed once. Only finalized story progress resets
the host budget; timestamps, messages and journal writes do not. Story repair/retry budgets
and completion gates remain unchanged. A busy turn is not a failed attempt.

After an explicit new human resume instruction, rearm the same binding with `host-bind`
and `resume_authorization_turn: "<that actual human turn UUID>"`, then reactivate the same
heartbeat. Do not reset spent attempts. No automatic `resume --confirm-cancelled`.

## Limits and acceptance

The app and machine must be available for local heartbeats. Closing the app, sleeping,
loss of access or a host failure can delay execution. Do not promise uninterrupted execution
or bypass Stop. Verify registration and busy-chat behavior separately from a real wakeup;
report an unobserved wakeup as unverified. Unit tests of the passive guard are not proof
that the app scheduler wakes the chat or that a whole epic completes.
