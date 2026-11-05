---
name: auto-bmad
description: Run a BMAD v6 story or epic through fresh isolated native Codex subagents. The main chat routes bounded tasks, slots, dependencies and user decisions; specialists perform planning, implementation, review, tests, integration and reporting. Requires BMAD planning and native agent tools. Push remains separate.
---

# Auto BMAD in Codex

Resolve this skill's real directory and retain the complete package layout. Read only
`HOST.md` and `../../../../skills/auto-bmad/ORCHESTRATOR.md` in the main chat. Full
`NATIVE.md`, `PARALLEL.md`, `REPORTS.md`, role prompts and rendered BMad workflow belong
to the finite specialists that need them; do not load them into the root to relay their work.

**The main chat is a thin router.** It owns scope, available slots, dependency admissions,
actual agent IDs, compact progress and user decisions. Bootstrap, planning, diagnosis,
triage, review revalidation, tests and test waits, integration, tracking and finalization
all run in fresh isolated native subagents using the existing configured role models/effort.
Do not read source, diffs, reports, full journals or logs; do not run tests or merge yourself.
An unresolved technical detail requires another bounded specialist task.

Prepare a bootstrap envelope using `<package>/bin/auto-bmad --executor codex native
task-prepare --repo <absolute-project-root> --arg "<user arguments>" --checkpoint bootstrap
--host-limit <actual-global-slot-limit>`. Add the actual paired `--root-thread-id` and
`--root-turn-id` if exposed, otherwise `--accounting-unavailable-reason "<actual reason>"`.
Follow ORCHESTRATOR.md's prepare/start/result/terminal-stop protocol. For a planning-only request add
`--planning-only`; it authorizes no journal initialization or worktree mutation. Execution authorizes its native subagents and required local checks within
scope. Missing tools, profiles or BMad inputs are explicit blockers; there is no CLI model
fallback and no silent profile/executor change. Preserve Claude settings. A finite finalizer
saves finish artifacts and its completion batch, then returns `ready`; root observes terminal
completion, calls `task-result`, and mechanically submits that batch. The finalizer never
applies its own `complete`/`finalize` while running; the root makes no technical acceptance.

Every new checkpoint uses a fresh agent with `fork_turns="none"`, explicit configured model
and effort, zero child slots and a persisted bounded handoff. Do not follow up a completed
agent with a different checkpoint. Fill feasible slots in the current dependency wave; do
not allocate waiting controllers. Keep processing the whole authorized scope in this turn.
Use HOST.md's interruptible event wait, never a minute heartbeat or status polling loop.

For requested unattended execution or automatic technical recovery, read `CONTINUATION.md`
and attach one host-owned heartbeat to this root chat. A journal cannot restart a terminated
turn. Stop/interruption, required input and real blockers stop continuation. Keep existing
journals, topology and pinned runtimes unchanged; installing this version does not migrate
or restart active runs.

Report only confirmed changes in the user's language: story, role/agent, phase, attempt,
blocker and next action, with actual launched/active/finished counts. Relay the specialist's
final result with completed/remaining stories, commits, checks, unresolved decisions and
preserved branch/worktree paths. Do not invent phases, token usage or measured savings.
With explicit `execution.merge_policy="auto-main"`, dispatch local landing after all gates
pass; a specialist performs it. Push and deleting retained worktrees remain separate.
