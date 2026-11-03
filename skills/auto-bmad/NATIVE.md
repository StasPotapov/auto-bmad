# Native agent orchestration

The main chat owns the run. Each story runs inside a native `story-runner` subagent;
its implementation and independent reviews run in native children. Python helpers never
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

## Main chat: plan and prepare

1. Inspect the selected scope with the skill wrapper's `plan --repo <root> --arg "<arguments>"`.
   Preserve the requested story/epic and `fast`, `normal`, or `deep` level. Read the actual
   epics and sprint plan; do not invent acceptance criteria. Empty input selects the next
   unfinished story. Report an empty or ambiguous plan before creating agents.
2. Read role settings with `<auto-bmad> agent-config --repo <root> --level <level>`.
   Each role provides `model`, `effort`, `prompt` and `agent_type`. Inspect native collaboration
   tools and the actual global agent limit. Missing tools or unsupported models are blockers;
   no executable, CLI login or model subprocess is a fallback.
3. Build ordered dependency waves from the selected stories using `PARALLEL.md`'s dependency
   rules only. Unknown or overlapping scope stays separate in conservative mode. Respect
   `[run].parallel` and `width`, but reduce each wave to the capacity of the current host.
   Preserve order and explain the reduction. Initially validate a serial story before
   enabling concurrent stories in a newly installed native adapter.
4. Show the plan and initial progress table from `REPORTS.md`. Save the plan JSON outside
   tracked files, then initialize the durable session. The session records scope and evidence;
   it does not execute the plan. Preserve the returned session path throughout this run.
5. Prepare the run worktree with `<auto-bmad> worktree start <target> --repo <root>`.
   For concurrent stories use separate linked worktrees, seeded from the integration branch
   at its exact current commit. Use the worktree helper's documented commands and inspect
   its returned paths. Never reset an existing branch to recreate a run. Run preflight in
   the actual worktree and handle the reported blocker before starting implementation.
6. Resolve continuation with `<auto-bmad> spec --story <id> --repo <worktree>`.
   Pass an existing spec path for `resume` or `review`; do not replace it with a new intent.
   Handle `sync-only`, `skip`, duplicate specs and blocked specs explicitly. A `review` route
   keeps the spec's original baseline; a new story uses the worktree's exact starting commit.
7. Render the actual BMad workflow with `<auto-bmad> engine prepare --repo <worktree>
   --output <new-private-directory> --level <level>`. Bind the story to that worktree,
   baseline and manifest before delegation. The native manifest lists the rendered workflow,
   role profiles and active review layers. A prepared manifest is not proof of a completed story.

## Passive journal commands

The Codex wrapper and `<auto-bmad> native` expose the same passive helper:

```text
<session-helper> plan --repo <root> --arg "epic-1 --normal"
<session-helper> init --repo <root> --plan <saved-plan.json>
<session-helper> status --session <session.json>
<session-helper> record --session <session.json> --request <event.json>
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

Write each event to a private JSON file before `record`. Fields below are required:

| `event` | Fields besides `event` and `story` |
|---|---|
| `bind` | `worktree`, exact `baseline`, prepared `manifest` path |
| `phase` | `phase`: preflight, planning, implementation, review, repair, verification, finalization or blocked; blocked also needs `reason` |
| `agent` | `role`, actual `agent_id`, `status`: running, waiting, completed, failed or stopped |
| `review` | `layer`, `agent_id`, saved `report` path, `verdict`: pass or problem, `reviewed_tree` |
| `review-not-applicable` | conditional `layer`, exact `condition`, `condition_result: false`, `evaluated_by: main-chat`, current `reviewed_tree`, `evidence` path to saved reasoning |
| `repair` | `kind`: spec, review or tests; concrete `reason` |
| `retry` | concrete `reason`; charges the saved technical retry budget |
| `complete` | `spec` path; marks the isolated result verified, pending finalization |
| `finalize` | final integration `repo`, successful `finish_report` JSON path |

Capture `current_code_tree` from `status` before a reviewer starts and include that fingerprint
in its handoff. Save its report, mark the actual agent completed, then record `reviewed_tree`
from that handoff. Never replace it with a newer fingerprint to accept stale work. The helper
checks report hashes and requires a completed independent review/verifier role.
Agent-verifier layers use `verify:<name>`. Tests repairs require a recorded failing `check`;
rerun `check` after that repair before charging another attempt. The helper owns the persistent
repair counts and no-progress evidence; the main chat owns the decision and actual delegation.

## Native agent handoff

Use the active adapter's native spawn operation with an isolated task context, explicit
configured model/effort and a supported role. The Codex mapping is in its `HOST.md`; Claude
uses its native Agent type and resolved parameters. Read the role's `prompt` file and send
its body plus the native overrides below. Never assume a Claude plugin agent type exists
in Codex, or that YAML model aliases select a Codex model.

Each handoff contains:

- Role, story ID/title, level, language, exact task and acceptance criteria or spec path.
- Absolute worktree and integration roots, branch, original baseline, manifest/workflow
  paths, durable session path, and parent/root agent identifiers.
- File/module ownership, the fact that other agents share this filesystem, and a ban on
  reverting others' edits. Every command uses an explicit cwd; every file path is absolute.
- The allowed child-slot budget and the parent to contact before exceeding it.
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
- Use the adapter's message operation for progress and questions to the parent. Use its agent wait
  operation to await required children. Do not finish with "waiting" as the story result;
  do not poll shell processes or issue idle commands to keep a turn alive.
- Models and effort come from the native manifest. Native agents inherit parent permissions;
  reviewers are instructed not to edit, but do not have an independently enforced read-only
  sandbox. Compare repository state before and after review; investigate unexpected writes.
- Only one writer owns a story worktree at a time. The controller does not edit while an
  implementer owns it. Reviewers receive a fixed baseline and final diff without each
  other's reports. A failed or missing reviewer is not an empty successful review.
- Story agents never merge, update sprint tracking, push, change configuration to increase
  budgets, or take another story. The main chat owns integration and tracking.

The main chat reserves slots for downstream work. With a total limit of four, a normal
batch is main chat + one story-runner + up to two child roles. Review layers beyond the
available slots run in subsequent batches. For wider hosts, grant explicit child budgets
to concurrent stories; never fill every slot with controllers that all need workers.

## Progress, failures and continuation

Agents report every actual stage transition and material blocker to their parent/root:
`story`, `agent_id`, `role`, `phase`, `attempt`, `status`, `evidence`, `blocker`, `next_action`.
The main chat validates the message, saves the corresponding session event, and updates the
progress table. Preparation is not implementation; a child finishing is not a story completing.
Maintain a registry of actual spawned agent IDs to calculate launched/active/finished counts.

The main chat remains responsible when a child returns `blocked`. Inspect its evidence:

- An implementation/test defect gets a bounded in-place repair under the existing spec.
  Prefer the adapter's continuation operation on the same available implementer. If a new agent is needed, pass
  saved evidence and existing work, and identify it as a new agent rather than resumed context.
- An actual requirements conflict goes to the user with the concrete decision needed.
  Editorial disagreements become recorded questions when they do not prevent acceptance.
- An environment failure is diagnosed and repaired within the existing authorization.
  Missing access or rejected permission is reported with the exact failed operation.
- An interrupted or malformed agent result gets a bounded technical retry with preserved
  work. Record `retry` before the replacement/follow-up; `recovery_limits.technical` defaults to 3. Check whether the original agent is still active before replacing it. Never duplicate
  a writer, reset counters, silently restart implementation or retry an explicit cancellation.

Use independent configured `repair_limits`: defaults spec 2, review 5, tests 10,
no_progress 3. Charge before each repair batch, preserve counts across follow-up agents and
passes, and rerun the original failed check. Different error wording does not establish
progress. Do not rewrite requirements or weaken tests merely to get a pass. After test
repairs stabilize, repeat every active review layer and all required checks on the final code.

Save phase, agents, repairs and evidence as they occur. After compaction read the saved
session before making decisions. After interruption, inspect native agent status and the
worktree; resume existing agents when possible. Disk state restores the plan and evidence,
not the live memory of a terminated agent. Closing the app is not a background-run guarantee.

## Verification, finishing and integration

The story-runner returns the spec path, baseline, implementation commit, review reports,
check outcomes, repair counts, open questions and a short result. Validate these against
files and commits. Preserve required spec verification commands and all active review layers.
Use the session `check` action for configured command checks so it stores current evidence.
Run configured agent verifiers natively with their resolved role and original instructions.
Run device/browser checks serially because devices, ports and services may be shared.

For adbm/mockmatch, read and use the installed tool's own skill. Preserve its configured
visual/eyes role and native delegation rules. Do not invoke the removed CLI eyes helper,
substitute screenshots for an independent verdict, or bypass the tool's permission controls.
Record missing prerequisites and check policy explicitly; an unavailable mandatory check
cannot be reported as passed. Record agent-verifier evidence as `verify:<name>` reviews.

Record `complete` only after the worktree is committed/clean, the spec is done,
and the required reviews and command receipts match the final code. The main chat then
runs `story-finish` with the documented JSON contract in `SKILL.md` Step 4, omitting
Claude-only `--session ${CLAUDE_SESSION_ID}`. Check each returned step: a partial failure
is not success, and replaying the whole helper can duplicate hooks. Save the exact `story-finish` JSON response. `complete` leaves the story verified and the
session running; it does not report the epic complete. After tracking/integration, run
`check --session <session> --story <id> --repo <final-root>` and record `finalize` with that
`repo` and `finish_report`. If integration changed code, collect fresh independent review
reports against the final root and record their `worktree` field. The final gate checks
commit ancestry, done sprint tracking, current evidence and a clean worktree.

For concurrent stories, merge verified branches in planned order into the integration
worktree, inspect conflicts, and rerun affected checks on the combined code before closing
the wave. Keep stories visibly pending integration until then. Never reuse a child branch's
passing tests as proof that the combined result passes. Preserve incomplete worktrees.

With `execution.merge_policy="auto-main"`, a fully verified epic can land in local main
through `land` after checking its current state. A changed main requires integration checks.
A real blocker prevents landing; editorial open questions alone do not. Otherwise report
where the completed branch is ready for manual integration. Push and deployment are separate.
