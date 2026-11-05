# Native agent orchestration

The main chat owns the run. Each story has native `story-runner` checkpoints;
implementation and independent reviews run as configured native roles dispatched by the main chat. Python helpers never
start a model, decide the next story, or restart an agent. Client adapters bind this lifecycle to their native tools, role models and waiting rules.
The existing Claude entry in `SKILL.md` implements the same lifecycle with its established
Agent tools. Its journal migration is not implied by the Codex adapter's validation.

Resolve `<package>` from the installed skill's real path. In this document `<auto-bmad>`
means `<package>/bin/auto-bmad --executor <current-client>`, and `<session-helper>` means
`python3 -B <package>/scripts/native_session.py`. Use absolute project/worktree paths.
Use the active client's entry point to select its adapter. The journal commands below belong
to the `native` backend; the retained Claude entry uses its existing state helpers until that
adapter explicitly adopts this journal. AI Workspace can install the package but is not a
runtime dependency. Do not copy runtime paths from old reports; use the currently installed package unless
the user explicitly requested a pinned version. Keep an interrupted run's original package.

## Thin root and finite specialists

New native sessions use `orchestration_policy: "thin-root-v1"`. The main chat keeps only
scope, dependency waves, ownership, available slots, actual agent IDs, short dispatch/result
envelopes, blockers requiring the user and the next action. All substantive work belongs to
fresh isolated native subagents, including bootstrap, planning, diagnosis, triage,
revalidation, tests and their waits, integration, tracking and final reporting.
The root must not read source, diffs, full reports, rendered workflows, full journals or test
logs; it must not run checks, merge branches, or make evidence-based technical decisions itself.
A detail that matters to a decision requires a new bounded specialist task, not an exception
that moves the work into the root. Short transport/configuration receipts and summaries are
navigation, never substitutes for evidence validation.

| Finite task | Existing configured role | Responsibility |
|---|---|---|
| Bootstrap / dependency planning | `story-runner` | Read real epics/sprint plan, plan/preflight, initialize journal, prepare worktrees/manifests and dependency rationale |
| Story planning / workflow checkpoint | `story-runner` | Follow rendered BMad steps, preserve workflow state, prepare complete next-role inputs |
| Shared context | `context-compiler` | Compile only on a cache miss |
| Implementation / repair | `implementer` | Execute the whole scoped batch, preserve every finding and closure row |
| Independent review | exact layer role | Complete its original independent review scope/context restrictions |
| Triage / diagnosis / revalidation | `triager` | Inspect all findings, code and cumulative changes; save decisions and bound evidence |
| Checks / test-session waiting | `verifier` | Run/join managed checks, inspect all failures and save receipts; never make the root poll tests |
| Integration / tracking / finalization | `story-runner` | Inspect and combine verified branches, handle conflicts, prepare check handoffs, finish tracking and report |

These task names do not introduce model profiles. Preserve each existing role's configured
model/effort. Every task has a finite scope and zero child slots. It returns before its
requested downstream tasks start. Never use a waiting controller around another worker.
For every new checkpoint spawn a fresh isolated agent (`fork_turns="none"` in Codex).
Do not reuse a completed planning agent for triage, a completed implementer for a new repair
batch, or a completed verifier for integration. Follow-up is only for unfinished work within
the same checkpoint; steer a running agent without creating another checkpoint in its context.

Existing journals retain their original policy, topology and pinned runtime. Do not migrate
an active run, restart its agents, rewrite its journal or edit its old runtime merely because
the installed skill changed. Resuming it uses the original package and its original contract.
The retained Claude entry uses its established engine lifecycle until its adapter explicitly
adopts this journal; the thin-root policy is not a silent Claude migration.

## Bootstrap and preparation contract

The root resolves this package, inspects live native tools/slot capacity and obtains only the
configured role profile needed to dispatch bootstrap. A planning-only request authorizes only
planning, not worktree mutation or implementation. Dispatch a fresh `story-runner` with the
absolute project root, exact user arguments, host capacity, runtime path and authorized scope.
The root passes `task-prepare --host-limit <actual-global-limit>` from the live tool schema
and either paired actual `--root-thread-id`/`--root-turn-id` UUIDs or an explicit
`--accounting-unavailable-reason`. The helper persists these as `host_metadata`; bootstrap
must use them for the schedule and accounting, never guess IDs or capacity. Existing public
`--fast`/`--normal`/`--deep` flags and configured defaults retain their parser semantics.
The bootstrap specialist performs the following work and persists its full output; the root
receives only the compact plan, rationale, paths, blockers and next task envelopes.

1. Use the skill wrapper's `plan --repo <root> --arg "<arguments>"`. Preserve requested
   story/epic, level and actual acceptance criteria. Empty input selects the next unfinished
   story. Return empty/ambiguous/missing-input errors before starting story work.
2. Resolve `agent-config --repo <root> --level <level>`. Missing tools or unsupported profiles
   are blockers, never reasons to substitute a model or use a CLI model subprocess.
3. Read the relevant epic and `PARALLEL.md` dependency rules. Build ordered waves using
   configured parallel/width and actual host capacity. Unknown/overlapping scope stays separate
   in conservative mode. Width is a ceiling, not proof of independence. Include a concrete
   rationale for each wave. A four-slot host has room for root plus three finite workers;
   do not impose a serial pilot or reserve permanent controller slots.
4. For planning-only, save/return the plan and stop before session/worktree mutation.
   For execution, save the complete plan outside tracked files and initialize the session. Before binding
   stories, record session-level `schedule` (no `story`), for example:
   `{"event":"schedule","host_limit":4,"waves":[{"stories":["1-1","1-2","1-3"],
   "reason":"Independent modules; no shared contracts or assembly points"}]}`.
   Include every planned story exactly once in queue order, including singleton waves for
   serial/single-story runs. The journal validates width, slots, admission and worktree
   isolation; the specialist owns semantic dependency analysis. Return the plan to the root
   for display before dispatching story work. Bind `stats record` to actual root thread/turn
   UUIDs supplied in `host_metadata`; if unavailable, preserve its explicit reason and report
   token accounting unavailable. Never guess IDs. Repeat the binding on a real resumed turn.
5. Prepare the run worktree through `worktree start`; prepare concurrent story worktrees
   from the integration branch's exact current commit. Inspect helper-returned paths, seed
   settings and run preflight there. Never reset an existing branch to recreate a run.
6. Resolve `spec --story <id> --repo <worktree>`. Preserve existing spec paths for resume/
   review and the spec's original baseline. Handle sync-only, skip, duplicate/blocked specs
   explicitly. A new story uses its exact starting commit.
7. Run `engine prepare --repo <worktree> --output <new-private-directory> --level <level>`.
   Bind the worktree, exact baseline and manifest. A manifest is not proof of completion.
   Persist the full bootstrap state and bounded next-role inputs; return and release the slot.

## Persisted task envelopes

The root uses ORCHESTRATOR.md's `task-prepare`, `task-start` and `task-result` protocol;
it does not read this full workflow. Workers read their persisted task and role/workflow
inputs directly, wait for the actual start binding, and fill its exact `receipt_template`.
Preserve task/session/story/agent IDs, current tree and artifact hashes. Execution bootstrap returns
its created thin-root session; `task-prepare --planning-only` keeps `created_session: null`
and performs no journal initialization or worktree mutation. Only after actual host-observed completion may the root call
`task-result --agent-id <actual-ID> --confirm-completed`. Structural receipt validation never
replaces independent reviews or the journal's completion/finalization gates.

A host-observed failed/stopped task without a usable receipt is recorded through `task-stop
--task <task-file> --agent-id <actual-ID> --status failed|stopped --reason "<observed reason>"
--confirm-terminal`. Join actual terminal state first; this does not stop a live agent or
assert completion. Preserve history/evidence, charge the existing bounded retry budget and
use a fresh task only when recovery is authorized. Never turn explicit cancellation into
a technical retry. This terminal path does not require the failed worker to invent a receipt.
If the actual host state is completed but the receipt is missing/invalid, use `task-stop
--task <task-file> --agent-id <actual-ID> --status failed --host-status completed
--reason "<concrete receipt failure>" --confirm-terminal` after that explicit observation.
The journal preserves agent `completed` and task `failed`; it accepts no completion evidence
and invents no receipt. Host completed may pair only with task failed, never stopped. The
preserved failure permits a fresh authorized bounded task without relabeling the host state.

## Passive journal commands

The Codex wrapper and `<auto-bmad> native` expose the same passive helper:

```text
<session-helper> plan --repo <root> --arg "epic-1 --normal"
<session-helper> init --repo <root> --plan <saved-plan.json>
<session-helper> status --session <session.json>
<session-helper> summary --session <session.json> [--story <id>]
<session-helper> record --session <session.json> --request <event.json>
<session-helper> record-batch --session <session.json> --request <batch.json>
<session-helper> check --session <session.json> --story <id>
<session-helper> resume --session <session.json>
<session-helper> cancel --session <session.json>
```

Save the complete `plan` output, including its request, role settings, base commit and config hash.
`init` revalidates it; alternatively `init --repo <root> --arg "<arguments>"` plans immediately.
A second unfinished session is rejected rather than duplicating work. `status` reads disk state;
its `agent_liveness` is unknown until the main chat reconciles actual native agent IDs.
`resume` validates saved configuration and bindings; it does not launch agents.
`cancel` records cancellation only. Stop/join the real agents before cancelling the journal or
starting another run. `resume --confirm-cancelled` is allowed only after the user explicitly
asks to continue a cancelled run.

Prefer `record-batch`: write one private JSON object with a stable unique `batch_id` and
an ordered `events` array. Every event uses the same validation as `record`; all are saved
under one lock/write, or none are saved on error. Example for an observed checkpoint return:

```json
{"batch_id":"planning-1-1-result-1","events":[
  {"event":"agent","story":"1-1","role":"story-runner","agent_id":"actual-host-id","status":"completed"},
  {"event":"phase","story":"1-1","phase":"implementation"}
]}
```

Use actual host IDs. Combine already-observed related events (terminal agent + review + phase)
and independent results available at the same wakeup. Do not delay a blocker or durability
boundary to fill a batch. Save before handing off ownership, starting a repair/retry, waiting,
or integrating; never pre-record a launch/result that has not happened. Launch events still
need actual returned IDs. Checks and model launches are outside this passive transaction.
A rejected batch leaves disk unchanged; fix it before any dependent action. On an uncertain
write response, retry the identical batch with the same ID: it returns the original compact
receipt without charging counters again, even after completion. Reusing the ID with changed
events is rejected. A replay receipt describes that batch, not current state. `event_start`
and `event_end` are zero-based, half-open offsets in the event list, not a revision of checks.
Never edit/recycle a successfully used batch ID. Single-event batches are allowed.
Legacy `record` still accepts one event and returns full state for existing callers.

Use `summary` for the run table and `summary --story <id>` for a focused handoff, including
a fresh code fingerprint. The overview does not hash every worktree; it shows verdicts,
counters, blockers, active agents and detail pointers relative to the top-level session path.
The focused story view expands evidence paths and stale/unknown tree matches. Summaries
do not revalidate evidence or certify completion. Full history, terminal agents, findings
and test diagnostics remain in the session/referenced files. Only a finite diagnosis specialist may use full `status` when history is required; it reads
the relevant evidence and returns a compact decision. The root never expands the journal. Liveness always comes from host events/tools.

Fields below are required for each story event:

| `event` | Fields besides `event` and `story` |
|---|---|
| `bind` | `worktree`, exact `baseline`, prepared `manifest` path |
| `phase` | `phase`: preflight, planning, implementation, review, repair, verification, finalization or blocked; blocked also needs `reason` |
| `agent` | `role`, actual `agent_id`, `status`: running, waiting, completed, failed or stopped; optional actual Codex `thread_id` UUID |
| `review` | `layer`, `agent_id`, saved `report` path, `verdict`: pass or problem, `reviewed_tree` |
| `review-revalidate` | `layer`, original `source_tree`, current `reviewed_tree`, saved JSON `evidence`, `evaluated_by`: completed registered `triager` ID; optional final `worktree` |
| `review-not-applicable` | conditional `layer`, exact `condition`, `condition_result: false`, `evaluated_by`: completed registered `story-runner` or `triager` ID, current `reviewed_tree`, JSON `evidence` path |
| `repair` | `kind`: spec, review or tests; concrete `reason` |
| `retry` | concrete `reason`; charges the saved technical retry budget |
| `complete` | `spec` path; marks the isolated result verified, pending finalization |
| `finalize` | final integration `repo`, successful `finish_report` JSON path |

Capture `current_code_tree` from `summary --story <id>` before a reviewer starts and include that fingerprint
in its handoff. Save its report, mark the actual agent completed, then record `reviewed_tree`
from that handoff. Never replace it with a newer fingerprint to accept stale work. The helper
checks report hashes and requires a completed independent review/verifier role.
Agent-verifier layers use `verify:<name>`. Tests repairs require a recorded failing `check`;
rerun `check` after that repair before charging another attempt. The helper owns the persistent
repair counts and no-progress evidence; the root owns dispatch, while finite specialists
own technical decisions and user decisions stay with the user.

For localized fixes, preserve the independent report and use `review-revalidate` instead of
launching a second independent reviewer. Its evidence JSON records `kind: "targeted-fixes"`,
`evaluated_by: "<completed triager ID>"`, exact `story` and `layer`, original `source_tree`, current `target_tree`, a nonempty
`scope_reason`, `all_findings_addressed: true`, `checked_changes`, and `findings` rows with
`id`, `status` (`fixed`, `rejected` or `deferred`), and concrete `evidence`. A `deferred`
row additionally requires `blocking: false`, `mandatory_defect: false`, a nonempty `reason`
and `tracking`: the absolute path of an existing nonempty triage/open-questions file. This is an
explicit delegated technical decision, never permission to defer a mandatory defect. A problem report needs at
least one row; a clean report may have none. Account for every original finding; any valid
non-blocking deferral must remain in the triage/open-questions log and is not an unresolved
mandatory defect. Revalidation covers the cumulative delta from the original independent
review, even after several small batches. It is a fresh triager assessment retaining the original independent report, not a new
independent review pass. Preserve source and evidence files unchanged. This event cannot
replace `verify:<name>` agent-verifier evidence or required current command checks.
An existing independent report may be revalidated directly, including rejection-only triage
or localized integration changes; do not charge a fictitious repair attempt without repairs.
Extensive/risky/uncertain changes require actual independent review instead.

For `review-not-applicable`, save JSON binding `evaluated_by` to that completed registered
story-runner/triager, exact `story`, `layer`, `condition`, `condition_result: false`, current
`target_tree`, and a nonempty `scope_reason`. Both delegated events bind evaluator identity,
story/layer and tree in request/evidence; the helper rechecks provenance and evidence hashes
at completion. The triager writes evidence plus a bounded record-batch request path and returns. Only after
actual host-observed completion and task-result registration may the root mechanically invoke
`record-batch --request <path>` (or a fresh finalization worker apply it). The helper validates
evidence; a running triager cannot apply its own completed-evaluator event. The root records
the returned decision without reading reports or code.
A missing evaluator or malformed evidence requires a fresh specialist task; it never permits
the root to assert acceptance. Old sessions without `thin-root-v1` retain their old contract.

## Native agent handoff

Use the active adapter's native spawn operation with an isolated task context, explicit
configured model/effort and a supported role. The Codex mapping is in its `HOST.md`; Claude
uses its native Agent type and resolved parameters. Point the fresh worker to its role `prompt` file and the native overrides below;
the worker reads them directly. Do not paste full prompt/workflow bodies into the root. Never assume a Claude plugin agent type exists
in Codex, or that YAML model aliases select a Codex model.

Subagents are configured by their actual task IDs: `story-runner`, `implementer`,
`context-compiler`, `blind-hunter`, `edge-case-hunter`, `intent-alignment`,
`verification-gap`, `triager`, and `verifier`. Every review layer uses the same-named
subagent/profile at all levels. `fast`/`normal`/`deep` choose active layers. Model/effort
come from client defaults (Claude review defaults differ on deep) and explicit settings.
Do not group layers under generic
reviewer tiers. Register review evidence only from the agent assigned that exact layer.
For cached epic context, skip compilation as before; otherwise use `context-compiler`
and its configured model/effort, including on `deep`.

Each handoff contains:

- Role, story ID/title, level, language, exact task and acceptance criteria or spec path.
- Absolute worktree and integration roots, branch, original baseline, manifest/workflow
  paths, durable session path, and parent/root agent identifiers.
- File/module ownership, the fact that other agents share this filesystem, and a ban on
  reverting others' edits. Every command uses an explicit cwd; every file path is absolute.
- The allowed child-slot budget (zero for root-dispatched checkpoints), and the root to contact for role dispatch.
- Required outputs, evidence paths, repair counts and unresolved findings from this attempt.

The **story-runner must read and follow the rendered BMad workflow** from the manifest.
This is the same specification → implementation → review/triage → verification → completion
lifecycle. Do not replace it with an informal coding task. Follow the engine's review-layer
instructions, conditions, context restrictions and acceptance criteria.

Apply the active client adapter's transport overrides to shared role instructions. In Codex:

- `Agent`/`Task` delegation means the actual collaboration API. `Skill` invocation means
  read and follow the rendered workflow when no skill-invocation tool exists.
- No `EnterWorktree`, `ExitWorktree`, implicit cwd, sandbox pinning, automatic branch reset,
  Claude session ID, CLI bridge, or separate model process is assumed.
- Use the adapter's message operation for material progress and questions to the parent. Legacy
  controllers use its event wait to await required children; root-dispatched checkpoints return
  a handoff instead. Do not finish with "waiting" as the story result;
  do not poll shell processes or issue idle commands to keep a turn alive.
- Models and effort come from the native manifest. Native agents inherit parent permissions;
  reviewers are instructed not to edit, but do not have an independently enforced read-only
  sandbox. Compare repository state before and after review; investigate unexpected writes.
- Only one writer owns a story worktree at a time. The controller does not edit while an
  implementer owns it. Reviewers receive a fixed baseline and final diff without each
  other's reports. A failed or missing reviewer is not an empty successful review.
- Implementation/review agents never merge or update sprint tracking. Only a fresh explicitly
  assigned integration/finalization story-runner owns those operations. No task may push,
  increase budgets or take another story without its dispatch scope.

### Root-dispatched checkpoints and slot use

In scheduled runs, a story-runner is a finite checkpoint at its configured model/effort.
It reads the rendered workflow and performs its assigned bootstrap/planning/integration/finalization step;
triage, diagnosis and revalidation use fresh triager tasks. Each task
returns artifacts plus the next required role handoffs. It must not spawn children or
remain active waiting for them. Returning a checkpoint is not completing the story.
The root records its terminal state and dispatches the next roles directly with their own
configured model/effort and prompts. Start each new controller checkpoint with an isolated
context and the saved workflow state/evidence references. Continue the same controller only
for unfinished work within that checkpoint. This preserves BMad and role
profiles without spending a slot on an idle parent. Legacy unscheduled sessions retain their
original hierarchy; do not change a live run's topology implicitly.

Thin-root specialists use `task-binding --task <task.json> --wait-seconds 60` once to join
actual task-start without another root message; stop/report on timeout or cancellation.
Before their terminal answer, `task-receipt --task <task.json> --request <decision.json>`
fills binding/tree/hashes and checks the exact receipt contract. Request fields: `state`,
`next`, `actions`, `blocker`, `artifact_paths`, optional `created_session`. It rejects invalid
values; it never truncates decisions, drops artifacts or guesses a next role. A full report
or index keeps all evidence when more than eight files are relevant. Existing handwritten
receipts can use `task-preflight --task <task.json> --agent-id <actual-ID>`.

Add `--record-batch <hashed-artifact-path>` to either local preflight command for a saved
same-story batch. It simulates only this producer's completion in memory and runs the journal
gates without saving any journal state. Other live agents still block completion; required
reviews/checks, `checked_changes`, cumulative evidence and finish prerequisites remain.
Root may use `task-result ... --confirm-completed --record-batch <path>` after actual host
completion to register the receipt and apply that batch in one helper call. A failed batch
leaves the terminal receipt accepted and applies no batch events; its compact response says
`receipt_accepted=true`, `batch_applied=false`, `state=blocked`. Route to fresh diagnosis.
This does not replace actual terminal observation or revalidate stale artifacts by fiat.

Native thin-root verification selection includes committed, staged, unstaged and untracked
(nonignored) files. Direct `verify plan` calls before a checkpoint commit must pass
`--working-tree`; an empty baseline..HEAD alone cannot establish visual nonapplicability.
Legacy journal verification retains its original selection semantics.

The persisted task's exact `receipt_template` is the machine contract for thin-root tasks;
the compact chat return identifies its saved receipt and status. For legacy checkpoint
handoffs without a task envelope, the header overrides the shared whole-story header:
`CHECKPOINT: <bootstrap|preparation|implementation|review|triage|revalidation|checks|test-wait|integration|finalization>`, `STATUS: ready|blocked`, `STORY: <id>`,
`STATE: <absolute saved handoff path>`, `NEXT: <required role/action or concrete blocker>`.
Save the workflow cursor/completed steps, spec and original baseline, manifest, current tree,
all required layers and reports, unresolved finding IDs/closure evidence, check/log paths,
repair/retry counters and next-role inputs in the handoff file. Do not embed full reports/diffs
in the return. `ready` means this checkpoint returned; only journal gates complete a story.

### Context and message budget

The root keeps only the compact plan, dependency/ownership decisions, active IDs, bounded
dispatch/result envelopes and next actions. It never reads implementation diffs, source,
full test logs, reports, journals or rendered workflows. Workers read their required role/workflow/spec and
source directly from disk. Controllers receive only their story and requested checkpoint,
plus complete artifact references; no inherited epic chat or other stories' transcripts.
Read instructions once per fresh agent; re-read a source/report only if changed or needed
for a concrete decision. Reuse valid cached epic context; do not recompile it per checkpoint.

This is navigation, not lossy acceptance: the triager inspects ALL active-layer findings
and closure rows; the revalidation specialist inspects cumulative changed code and affected
tests; the integration specialist inspects conflicts, risk and required evidence. Specialists
expand their context whenever a missing detail affects their assigned decision. The root
dispatches another fresh specialist when an unresolved technical detail needs investigation. Never truncate away a blocker, finding,
acceptance criterion, required check, failed/absent review or non-blocking deferral. Reviewers
still receive their layer's exact required context (including blind-review restrictions),
fixed baseline/current tree and independent access to the full relevant code. Preserve all
configured models/effort, review layers, repair budgets and final gates.

Use one result/handoff per checkpoint. Send an extra message only for a meaningful stage
transition during a long task, blocker, required decision or changed ownership. Do not send
acknowledgements, repeated stage reports, "still running", or duplicate the final result in
a preceding message. The root coalesces related results into one journal batch and one
human update; update only changed table rows. Never emit an update just because a timer fired.

Fill free slots across the current dependency wave before giving a story extra reviewer slots.
With four total slots and width three: root + three planning checkpoints, then root + three
implementers in separate worktrees, then independent review batches. These are examples,
not a global phase barrier: as one role returns, dispatch another ready role from the same wave.
Before each spawn/follow-up, reconcile actual native liveness with journal agent events. Only
terminal/joined agents release slots; `waiting` consumes one. Record each actual launch, including
its thread UUID when available. The journal rejects over-budget events and an active controller
or writer overlapping other roles of the same story. Do not spawn and only then discover there
is no capacity. Device/browser verification remains serial across stories; other ready work can
use spare slots. Dependencies and shared files still limit wave width. Never omit reviews to fit
slots and never start a later wave before the previous wave is integrated and finalized.

## Progress, failures and continuation

Agents report every actual stage transition and material blocker to their parent/root:
`story`, `agent_id`, `role`, `phase`, `attempt`, `status`, `evidence`, `blocker`, `next_action`.
The main chat validates the message, saves the corresponding session event, and updates the
progress table. Preparation is not implementation; a child finishing is not a story completing.
Maintain a registry of actual spawned agent IDs to calculate launched/active/finished counts.

The main chat remains responsible when a child returns `blocked`. Route its compact blocker
and evidence paths to a fresh diagnosis/triage specialist when technical analysis is needed:

- An implementation/test defect gets a bounded in-place repair under the existing spec.
  Use a fresh implementer for each new repair checkpoint with saved evidence and existing work.
  Continue an available agent only for unfinished work within that same checkpoint.
- An actual requirements conflict goes to the user with the concrete decision needed.
  Editorial disagreements become recorded questions when they do not prevent acceptance.
- An environment failure is diagnosed and repaired within the existing authorization.
  Missing access or rejected permission is reported with the exact failed operation.
- An interrupted or malformed agent result gets a bounded technical retry with preserved
  work. Record `retry` before the replacement/follow-up; `recovery_limits.technical` defaults to 3. Check whether the original agent is still active before replacing it. Never duplicate
  a writer, reset counters, silently restart implementation or retry an explicit cancellation.

Use independent configured `repair_limits`: defaults spec 2, review 5, tests 10,
no_progress 3. Charge before each repair batch, preserve counts across follow-up agents and
passes. Collect ALL active-layer reports before triage; collect ALL known test failures
from a completed run before fixing. Send the whole actionable list in one repair batch.
A partial implementer handoff continues that batch and counter; do not start review or
spend another review attempt for a known item that was left unfinished. Track every finding
by ID, fix/evidence and check result; keep the original triage rows when grouping duplicates.
The fresh triager accepts technical rejections or non-blocking deferrals only with concrete
evidence; actual requirements decisions go to the user through the root.

Fix the entire known failing-test set before rerunning the failed commands and affected
regressions. Focused diagnostic runs are allowed when necessary, but are not a new batch.
New failures exposed by the rerun may need another batch. Different error wording does not
establish progress. Do not rewrite requirements or weaken tests merely to get a pass.

The first independent review is mandatory. Repeat it only after extensive or risky changes:
new behaviour/contracts, broad data/control-flow changes, auth/security, schema/migrations,
nontrivial conflict resolution or uncertain impact. Judge cumulative changes since the last
independent review, not the latest tiny patch. For localized corrections with understood
impact, a fresh triager inspects all fixes and closure rows and saves delegated revalidation
evidence for every retained layer; a finite verifier reruns affected tests. The root records
`review-revalidate` only with the completed evaluator ID and valid persisted evidence. Severity or finding count alone never triggers a
repeat. For integration-full-v1 use focused checks/build after the repair batch; run the full
gate only on the final integration candidate before landing (or a documented broad-risk exception).

Save phase, agents, repairs and evidence as they occur. After compaction read the saved
compact session summary; delegate evidence/worktree inspection to a fresh recovery
specialist. After interruption inspect native agent status, then resume only unfinished work
within an existing checkpoint when possible. Disk state restores the plan and evidence,
not the live memory of a terminated agent. Closing the app is not a background-run guarantee.
An adapter may attach a host-owned continuation when the user requests unattended work.
The Codex contract is `integrations/codex/skills/auto-bmad/CONTINUATION.md`: the host schedules
wakeups; passive `host-bind`/`host-recover` commands guard ownership, cancellation and retries.
They never launch models or change a story's evidence gates. An interrupted root turn must
not be silently treated as a recoverable technical failure.

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

Command checks hold a separate lock for their worktree, not the shared journal lock.
The journal is locked only to prepare and publish a check; agent dispatch and review
receipts can proceed while tests run. Checks in separate worktrees may overlap; duplicate
checks of one worktree wait and then re-read the saved result. Publication re-reads the
journal, preserves concurrent events and rejects results after cancellation/resume, repair,
relevant state changes or code/config changes. A rejected result is not passing evidence.
An execution checkpoint saved before test launch retains the managed run ID even when
publication is rejected; the next authorized matching check joins it. A different check
cannot replace that checkpoint while tests are still running in the same worktree.
Existing runs keep their pinned runtime; installing an update does not change live checks.

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

## Verification, finishing and integration

The story-runner returns the spec path, baseline, implementation commit, review reports,
check outcomes, repair counts, open questions and a short result. A fresh finalization
specialist validates these against files and commits; the root sees its compact receipt. Preserve required spec verification commands and all active review layers.
A finite verifier uses session `check` for configured command checks so it stores current
evidence. That task owns test launch, managed session joins/waits, failure collection and
receipts. The root never runs/polls these checks. Dispatch configured agent verifiers with
their resolved role and original instructions.
Run device/browser checks serially because devices, ports and services may be shared.

For adbm/mockmatch, read and use the installed tool's own skill. Preserve its configured
visual/eyes role and native delegation rules. Do not invoke the removed CLI eyes helper,
substitute screenshots for an independent verdict, or bypass the tool's permission controls.
Record missing prerequisites and check policy explicitly; an unavailable mandatory check
cannot be reported as passed. Record agent-verifier evidence as `verify:<name>` reviews.

A finite finalization specialist checks that the worktree is committed/clean, the spec is
done and required reviews/check receipts match current code. It saves the requested
`complete` event in a `record-batch` request and returns `ready`, with that path in its bounded
receipt. It must not apply `complete` or `finalize` while its own agent is running. Root first
observes actual terminal completion, calls `task-result --confirm-completed` with the actual
agent ID, then mechanically submits the saved batch. Only the journal gate marks the story
verified; `complete` still leaves integration/finalization pending. The root does not read
source/evidence or make technical acceptance decisions.

For tracking/finish, the assigned finite story-runner runs `story-finish` with `SKILL.md`
Step 4's JSON contract, omitting Claude-only `--session ${CLAUDE_SESSION_ID}`. Inspect each
returned step and save the exact response: partial failure is not success, and replaying the
whole helper can duplicate hooks. Return before a verifier runs required final-root checks
through `check --session <session> --story <id> --repo <final-root>`. A fresh finalization
specialist inspects those completed receipts and actual finish artifacts, writes the
`finalize` batch with `repo`/`finish_report` (and `complete` first if not yet recorded), and
returns `ready`. Root observes terminal completion, accepts only the structural `task-result`
receipt, and mechanically invokes `record-batch --request <saved-path>`. All gates still
validate current checks, ancestry, done tracking, clean worktree and absence of active agents.
A rejected batch requires a fresh finite diagnosis task; no task or root may bypass the gate.

If integration changed code, a fresh triager assesses cumulative risk: extensive/risky changes
require fresh independent reports; localized corrections permit explicit `review-revalidate`.
Record the final root as `worktree` in either case and obtain required current check receipts
before preparing finalization. Completion and finalization requests are prepared evidence,
not successful gate results until the root's mechanical submission passes.

For concurrent stories, a fresh integration story-runner merges verified branches in planned
order and inspects conflicts. It returns before a verifier runs affected checks on the combined
code; a fresh finalization task closes the wave only after those checks. Keep stories visibly pending integration until then. Never reuse a child branch's
passing tests as proof that the combined result passes. Preserve incomplete worktrees.

With `execution.merge_policy="auto-main"`, a fully verified epic can land in local main
through `land --native-session SESSION --story ID ...` in a fresh integration task after inspecting its current state. A changed main
requires integration checks by a verifier and finalization by a fresh specialist.
A real blocker prevents landing; editorial open questions alone do not. Otherwise report
where the completed branch is ready for manual integration. Push and deployment are separate.
