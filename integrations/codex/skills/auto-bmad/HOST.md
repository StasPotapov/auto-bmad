# Host capability contract

Resolve this skill's real path before resolving relative resources. Keep the complete
package layout; a copied SKILL.md is not an installation. The package is versioned
code: outputs, caches, credentials and user data belong outside it. Use Python with
`-B` or `PYTHONDONTWRITEBYTECODE=1` when running packaged scripts.

Use the current host's file, shell, image, question and background-session APIs.
Names such as Read, Bash, Glob, Task or Artifact in older examples describe a
capability, not a required tool name. Inspect the actual tool schema before calling.
For subagents use the current collaboration API, including its wait and follow-up operations.
Do not copy Claude-specific end-of-turn notification rules into Codex. Without an
image viewer, do not claim a visual check. Without a connector, use the documented
local-file route or report the missing dependency. Do not invent tool calls.

Agent prompts are shared resources; client-specific model names, effort and launch
APIs belong to the current host's adapter. Codex-specific examples apply only in
Codex. On Claude Code use its installed native agent and configured model; on other
hosts use a verified agent adapter. Never translate model names by guesswork.
If independent agents or required isolation are unavailable, report that limitation;
a local deterministic result is not an independent visual verdict. Hook files also
need native installation and trust; their presence alone does not enforce a guard.

Dependencies are not bundled executables. Check the tool's documented prerequisites;
installing this skill does not authorize logging in, changing devices or services,
installing system software, publishing, or switching an existing executor.

## Native Codex execution

Before a run, verify that `spawn_agent`, message, wait, and follow-up tools are available.
Use `fork_turns="none"` with explicit configured `model` and `reasoning_effort` when supported.
Give every child its role instructions, task inputs, absolute worktree path and ownership boundaries.
A role's YAML header does not select the Codex model. Never substitute an unsupported profile.

Subagents share the filesystem and inherit this chat's permissions. An absolute worktree path in a
prompt does not change the child's working directory: use absolute paths and explicit command cwd.
A review instruction forbidding edits is not a separate read-only sandbox. Verify that review did
not change tracked or untracked work; stop and inspect any unexpected changes before accepting it.

The main chat owns the global slot budget. Count itself and all running/waiting roles.
Use NATIVE.md's root-dispatched checkpoints for scheduled epics: controllers return before
workers launch, and the root dispatches configured roles directly. A four-slot host can run
three independent stories with one role each; do not spend a permanent slot on each controller.
Save the dependency schedule and reconcile actual liveness before dispatch. Batch independent
review layers when slots are full. A smaller feasible wave never permits omitting a layer.

Native capability mapping for this adapter:

| Shared capability | Codex operation |
|---|---|
| Spawn isolated role | `collaboration.spawn_agent`, `fork_turns="none"`, explicit `model`/`reasoning_effort` |
| Send progress or steer active child | `collaboration.send_message` |
| Continue an idle child | `collaboration.followup_task` |
| Wait for results | `collaboration.wait_agent` |
| Inspect active agents | `collaboration.list_agents` |
| Stop active child | `collaboration.interrupt_agent`, then inspect/join actual result |

Read the live tool schemas before calling them. This mapping is an adapter, not a new
workflow. Shared BMad role prompts, acceptance rules and repair policies stay in the package.

### Event-driven waiting (required)

When no authorized work is ready, wait for a native agent/user event, not a timer-driven
status loop. With `collaboration.wait_agent`, explicitly request the longest interruptible
wait allowed by the live schema and higher-priority host instructions (currently the API
supports `timeout_ms=3600000` and wakes early for agent messages/results or user input).
Never use the short default/60-second waits as a heartbeat. If the host imposes a shorter
ceiling, obey it: a timeout is not progress. Silently re-arm the event wait without a status
message, `list_agents`, journal read/write, shell sleep or "still waiting" message to a child.
Do not claim zero timeout wakeups when the host itself requires them.

On an event, consume new messages/results once, record actual changes together, dispatch
ready work, then wait again. Inspect liveness only for dispatch, recovery, cancellation or
a concrete failure suspicion, not periodically. Do not echo wait-tool status to the user.
Never call `followup_task` merely to ask for progress: it starts another model turn.
Checkpoint controllers return their handoff and release their slot; only the root waits.
For command sessions use the host's completion notification/interruptible wait when exposed;
otherwise use the longest permitted wait on the same session, without repeated empty polls,
new test launches, shell sleeps or user-facing updates on timeouts.
