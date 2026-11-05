# Running in Codex

[Русский](../ru/codex.md) · [Back to README](../../README.md)

Use `$auto-bmad epic-1 --normal` or `$auto-bmad 1-3` in a Codex chat.
The main chat routes compact task envelopes, slots, dependency waves and user decisions.
Fresh isolated native subagents do all substantive work: bootstrap, planning, implementation,
independent review, triage/revalidation, tests and their waits, integration and final reporting.
Each task uses its existing configured role model/effort and returns before downstream work
starts. The root never reads source, diffs, full reports/journals or logs and never runs tests
or merges. Existing journals retain their original policy, topology and pinned runtime.

The root waits for agent/user events using the longest allowed interruptible native wait
(current API maximum: 3600000 ms), without a minute heartbeat. Guidance limiting blocking
shell waits to 60 seconds does not cap this interruptible API. Explicit hard host caps still
apply and are reported; they can prevent a guarantee of zero timeout wakeups.

The chat maintains a progress table: story, agent, phase, attempt, blocker and next action.
Parallel stories use separate worktrees. The actual wave width respects host capacity and
reserves room for downstream workers and reviewers. Python helpers prepare worktrees,
run tests, validate evidence and save state; they do not launch models or own the story queue.
The old Codex CLI pipeline is removed from the active runtime. There is no `codex exec` fallback.

Use `$auto-bmad-setup` to configure the project. Codex selects `execution.backend="native"`
for the invocation, preserving Claude settings and the stored project default. Existing model
and effort choices survive compatible CLI-era configuration migration. Shared values belong
in `.auto-bmad.toml`; machine overrides belong in the ignored `.auto-bmad.local.toml`.
The project still needs BMad planning and the actual native collaboration tools.

Landing is manual by default. `execution.merge_policy="auto-main"` lets the root dispatch
a finite specialist to land a verified epic in local main after integration checks. Push remains separate. Saved state helps
resume interrupted work; it does not guarantee autonomous execution after the app closes.
Native token usage is reported only when the host exposes measurements.

For requested unattended runs, the Codex adapter can attach a native heartbeat to the
original chat to recover confirmed technical failures or premature final responses.
It preserves saved work and bounds retries; Stop/interruption and required user decisions
stop the epic. The app must support local heartbeats and remain available. See the
[continuation contract](../../integrations/codex/skills/auto-bmad/CONTINUATION.md).

See the [native workflow](../../skills/auto-bmad/NATIVE.md), [helper reference](cli.md#native-codex-orchestration),
[installation](install.md#codex-and-local-skill), and [model settings](config.md#compact-codex-models).
