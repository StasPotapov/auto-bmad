# Thin native root: dispatch contract

This is the root's routing reference for new `thin-root-v1` native sessions. Full workflow,
role instructions and evidence stay with fresh finite specialists. Existing sessions use
their original pinned runtime and policy; never migrate or edit a live old runtime.

1. Resolve `<auto-bmad>` as `<installed-package>/bin/auto-bmad --executor codex`. Inspect
   actual collaboration tools and global slot capacity. Root counts as one slot; every
   running/waiting agent counts too. Missing tools/profiles block execution; no CLI fallback.
2. Prepare bootstrap: `<auto-bmad> native task-prepare --repo <absolute-root>
   --arg "<exact user arguments>" --checkpoint bootstrap --host-limit <actual-global-limit>`.
   Use the live host's total capacity, including root, never a guessed default. When exposed,
   pass both `--root-thread-id <actual-UUID>` and `--root-turn-id <actual-UUID>`; otherwise
   pass `--accounting-unavailable-reason "<actual reason>"`. Never invent UUIDs. The helper
   persists this `host_metadata` for schedule/accounting. Public `--fast`, `--normal`,
   `--deep` and configured defaults in `--arg` keep the existing parser semantics.
   The bounded response contains `task_file`, `phase`, `status` and `spawn` arguments.
   For planning-only add `--planning-only`; no session initialization/worktree mutation.
3. Call `collaboration.spawn_agent` with the returned `spawn` fields: `task_name`, configured
   `model`, `reasoning_effort`, `fork_turns="none"`, and the short `message`. Then bind the
   actual returned host ID: `native task-start --task <task_file> --agent-id <actual-ID>`.
   `display_name` is report metadata, for example
   `13.6 Impl [Sol·m]`, using the actual configured model and effort (high becomes `h`).
   Known model families keep their names: Sol, Terra, Luna, Astra; other versions retain
   a version suffix and unknown models/efforts remain literal. Review roles remain distinct:
   Blind, Edge, Intent, Gap. Do not pass display_name as an unsupported spawn field.
   The supported `task_name` uses those compact labels: `13_6_impl_sol_m` or
   `bootstrap_runner_sol_m`. Repeated names receive `_2`, `_3`, etc., reserved atomically
   across the repository's bootstrap and session journals. UUIDs and receipt hashes remain separate.
   If that name is already known in this host (for example from another repository),
   or spawn explicitly rejects a duplicate, append the next unused ordinal and bind the
   actual returned host ID. Use already known host names; do not add a discovery poll.
   Do not rename worker/root threads to change an agent card. Report metadata and thread
   titles do not prove the card changed; verify the actual spawn name and distinguish it
   from a visual UI check.
   The worker calls `task-binding --wait-seconds 60` once; task-start writes sibling
   `binding.json`, so no extra binding message is needed. This is finite local file waiting,
   not a model polling loop. On timeout/cancellation it stops and reports; do not retry a
   timer loop. Preserve the actual `task_hash`, `agent_id` and `result_file`. Never pre-record
   a launch or invent an ID. Each task has zero child slots.
4. Only after observing actual terminal completion through native tools, call `native
   task-result --task <task_file> --agent-id <actual-ID> --confirm-completed` (optionally
   `--receipt <path>`). The flag asserts the host observation, not root technical acceptance.
   Consume its bounded routing receipt only. The worker uses `receipt_template` from its
   task file, including task/session/story/agent bindings, current `tree` for a bound story,
   `created_session` for successful execution bootstrap (null with `--planning-only`), and
   artifact SHA-256 hashes. The receipt
   carries `state`, `next`, up to four short `actions`, `blocker` and up to eight artifact
   references. Helper stdout is capped at 4096 UTF-8 bytes; the receipt at 16384 bytes.
   Full reports stay unlimited on disk. Specialists use `task-receipt` for deterministic
   construction and local preflight before returning; errors belong to the still-running
   specialist, without a root follow-up to repair JSON. Structural provenance is not a
   completion gate. For a specialist's authorized saved batch, add `--record-batch <path>`
   to task-result: the request must be a hashed receipt artifact for this story. The helper
   registers observed completion first, then applies existing atomic journal gates. A gate
   rejection returns `receipt_accepted=true`, `batch_applied=false`, `state=blocked`; dispatch
   a fresh diagnosis, never retry task-result or invent acceptance. The accepted receipt
   remains terminal and the rejected batch changes no journal events. Existing record-batch
   remains available for explicitly prepared recovery requests and idempotent replay.
   If the actual host reports failure/stopping without a usable receipt, use `native task-stop
   --task <task_file> --agent-id <actual-ID> --status failed|stopped --reason "<observed reason>"
   --confirm-terminal` only after observing and joining that terminal state. It preserves
   history and frees the task for a bounded retry; it never claims successful completion.
   If the host actually completed but its receipt is missing/invalid, use the same command
   with `--status failed --host-status completed --confirm-terminal` and the concrete receipt
   failure reason. This records agent `completed` but task `failed`, accepts no evidence and
   fabricates no receipt. `--host-status completed` is valid only with task `--status failed`,
   never `stopped`. After explicit terminal observation, authorized bounded recovery may
   dispatch a fresh task. Explicit cancellation still stops the run; no automatic retry.
5. Prepare each next task with `native task-prepare --session <session> --story <id>
   --role <configured-role> --checkpoint <checkpoint> [--input <persisted-json>]`.
   Use the dependency/ownership plan and next-role inputs produced by specialists. Persist
   scope, host capacity and permitted actions in those inputs. When the saved handoff already
   determines the next authorized role/checkpoint, perform result/optional batch and prepare
   sequentially in one tool execution, branching on the bounded success response. Do not
   prepare after a blocked/failed response or invent routing; never batch host terminal
   observation, spawn or authorization assertions. Independent task preparations may share
   one tool execution subject to capacity and dependency gates. Do not copy full documents
   through the root. If a required decision lacks evidence, dispatch a fresh specialist.
6. Reconcile actual native liveness at dispatch/recovery/cancellation boundaries. Only
   terminal/joined agents free slots. Admit work within the current saved dependency wave;
   never admit a later wave until integration and finalization of the current wave pass.
   Dispatch independent review layers in batches when slots are limited; never omit one.
7. Persist observed state through compact `record-batch` receipts and use `summary` for
   navigation. Never open full journals, source, diffs, reports, logs or workflow artifacts.
   Technical acceptance, repairs, test sessions, merges and evidence inspection belong to
   specialists. Gate rejection goes back as a bounded diagnosis task, not root investigation.
8. When no authorized task is ready, use HOST.md's longest allowed interruptible event wait.
   No timer-driven progress messages, minute heartbeat, empty polling or status rereads.
   Consume each new result once, dispatch ready work, then wait again.

Use existing configured roles: story-runner for bootstrap/preparation/integration/finalization;
implementer for implementation/repair; exact layer roles for independent review; triager for
triage/diagnosis/revalidation; verifier for checks/test-wait; context-compiler for uncached epic
context. `--checkpoint` values are bootstrap, preparation, implementation, review, triage,
revalidation, checks, test-wait, integration and finalization. Diagnosis is a scoped triage
input; context compilation is a scoped preparation input. Do not introduce new model profiles.
Every new checkpoint starts fresh; follow-up is only for unfinished work inside the same task.
A controller returns before downstream workers start. The root alone waits for agent events;
a finite verifier owns command-session/test waiting without delegating a waiting controller.

Technical revalidation uses a completed registered triager ID, not `main-chat`; conditional
review applicability uses a completed story-runner/triager ID. Full evidence is persisted and
validated by helpers. A triager saves its evidence and record-batch request then returns;
only after observed completion and task-result registration may the root mechanically pass
that request path to record-batch, or assign its application to a fresh finalization task.
Completion has the same ordering: a finite finalizer inspects evidence, performs assigned
finish work, saves actual finish artifacts and a `record-batch` request for `complete` and/or
`finalize`, then returns `ready`. It must not apply its own completion events while running.
After actual terminal completion, root calls `task-result` and mechanically submits the saved
request path from its bounded receipt with `native record-batch --session <session> --request
<path>`. Journal gates validate all evidence and absence of active agents. Gate rejection
requires a fresh specialist; it never permits root technical acceptance or a false success.
Initial independent reviews, command/agent checks, cumulative-risk rules, repair budgets and
final clean/tracking/ancestry gates remain mandatory.

Show confirmed plan/progress and actionable decisions in the user's language. Ask only for
real missing authorization/requirements/access decisions. For cancellation, stop admissions,
steer/interrupt and join actual agents, preserve work, then record cancellation; never recover
an explicit stop automatically. Host-owned unattended recovery is opt-in (CONTINUATION.md).
Relaying the finite finalization task's concise report is the root's final action; do not read
its full artifacts to rewrite it. No push or deployment beyond the user's authorized scope.

New sessions use integration-full-v1: request focused/build evidence during story work and a
single full gate per actual combined landing, before main changes. Never dispatch habitual
per-story full runs. Preserve existing wave barriers and landing mode. Specialists own the
registered check plan and broad-risk exceptions. Dispatch the existing guarded land command
with its native session and complete included story list; finalization consumes shared
exact-candidate evidence rather than launching the same full suite again.
