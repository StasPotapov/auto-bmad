# Configuration

[Русский](../ru/config.md) · [Back to README](../../README.md)

The config is optional: without it a run works on the built-in defaults. It sets:

| Section | What it sets |
|---|---|
| [`[run]`](#run) | the default level, parallel waves and wave width, triage of review findings in a subagent |
| [`[roles.*]`](#roles) | legacy Claude model and effort overrides for each semantic subagent |
| [`[executors.codex]`](#compact-codex-models) | models and effort per semantic subagent, with shared defaults and explicit level overrides |
| [`[repair_limits]`](#repair_limits) | independent spec, review and test budgets per story |
| [`[verify_limits]`](#verify_limits) | deprecated; replaced by repair_limits |
| [`[[verify]]`](#verify) | checks after a story: project tests, Android emulator, browser, your own commands |
| [`[[hook]]`](#hook) | your scripts on run events: a chat message, a task board update |

`/auto-bmad:setup` writes the project file `.auto-bmad.toml` from what it finds in the project.
You can also write it by hand: take one of the [examples](#example-android-project) below.
After an edit, check the result with `auto-bmad ext config --repo .`; the model and effort of
the roles — with `auto-bmad roles --repo .`.


## Compact Codex models

Codex includes [per-subagent defaults](levels.md#models): Sol/medium for story-runner, intent-alignment and verifier; Sol/high for implementer, verification-gap and triager; Luna/high for context-compiler; Astra/high for blind-hunter and edge-case-hunter. Explicit common model/effort settings override these defaults for their group; role settings remain more specific.
Native agents inherit the parent chat's permissions; reviewer no-edit instructions are not a separate sandbox.
Claude keeps its client-specific model defaults; shared role instructions live in `prompts/roles/`.
Use the defaults or write only differences:

```toml
[executors.codex]
model = "gpt-6.1-sol"
effort = "high"
review_model = "gpt-6-astra"
review_effort = "high"

[executors.codex.levels.fast]
effort = "medium"

[executors.codex.levels.deep]
review_effort = "xhigh"
```

The common block applies to fast, normal and deep. A missing level inherits it.
Work effort and review effort are independent. Shared values are defaults, not agent identities.
Each actual subagent has its own role table. For example, these two review layers can use
different effort values without changing any other layer:

```toml
[executors.codex.roles.blind-hunter]
model = "gpt-6-astra"
effort = "high"

[executors.codex.roles.edge-case-hunter]
model = "gpt-6-astra"
effort = "xhigh"

[executors.codex.levels.deep.roles.edge-case-hunter]
effort = "max"
```

Use the same IDs under `[executors.claude.roles.<id>]` with Claude model aliases.
The level controls enabled checks and depth; it never replaces the layer ID with a model tier.
Resolution is built-ins → common → level → common role → level role. Local file values
first override project values. Unknown levels, roles and keys are rejected, even when inactive.

Setup uses private `.auto-bmad.local.toml` for client model settings by default.
`setup agent --agent codex --role edge-case-hunter --model gpt-6-astra --effort high`
previews one subagent; `--write` saves it. Add `--level deep` for an explicit override at that level.
`setup agent --agent codex --level fast --effort medium` changes the level's shared work defaults.
An explicit `--layer project` retains shared configuration support. Native Claude settings use
`[executors.claude]` with common, level and role overrides; legacy `[roles.*]` remain a fallback.
Both client namespaces coexist, and configuring one must preserve the other.

`setup agent --agent codex --compact` migrates compatible advanced routes with an exact backup.
It preserves model/effort per role and level. Unsupported adapters or incomplete routes are refused.
Executable, environment and CLI timeout fields are inactive in native mode; setting their old
CLI flags is rejected. Do not silently translate another client's model names.
The active skill selects its own client without changing the saved project default.
The native Codex backend uses chat subagents; old `backend="cli"` is read-compatible with a warning.
AI Workspace is an installer, not a runtime dependency.

## Four layers

auto-bmad reads four TOML files. Each next layer wins over the previous one.

| Layer | File | For |
|---|---|---|
| defaults | `defaults.toml` in the plugin | built-in checks and limits; do not edit |
| personal | `~/.config/auto-bmad/config.toml`, or the file in `$AUTO_BMAD_CONFIG` | your own hooks and preferences on this machine |
| project | `.auto-bmad.toml` in the repository root | project settings shared by every machine; commit it |
| local | `.auto-bmad.local.toml` in the repository root | this machine only, over the project file: another test command, another model, a check off here; keep it out of git |

Merge rules:

- Tables (`[run]`, `[roles.*]`, `[verify_limits]`) merge by key.
- Arrays of tables `[[verify]]` and `[[hook]]` merge by the `name` field: a block with the
  same `name` adds and overrides fields; a new `name` adds a new block.
- `enabled = false` turns a hook or check off.
- Any other value (including plain arrays such as `apis`) is replaced.
- A layer that cannot be read is skipped with a warning; the run goes on.

See the merged result and which files were used:

```bash
auto-bmad ext config --repo .
```

Every command that reads the config (`plan`, `profile`, `preflight`, `roles`, `verify`,
`land`, `ext`) sees the local layer. `auto-bmad setup local --write` closes it from git (adds
it to `.gitignore`); preflight warns when it is committed. A
[run in its own worktree](running.md#run-in-its-own-worktree) copies it into the worktree.

Turn off a personal hook in one project — in that project's `.auto-bmad.toml`:

```toml
[[hook]]
name = "notify"
enabled = false
```

`@plugin` in `command`, `detect` and `instructions` expands to the plugin's install
directory. Use it instead of a cache path, which changes with every update.

## `[run]`

Run defaults. Flags of the command (`--fast`, `--deep`, `--no-parallel`, `--width N`, …) win.

| Key | Values | Default |
|---|---|---|
| `level` | `fast`, `normal`, `deep` | `normal` |
| `parallel` | `conservative`, `aggressive`, `off` | `conservative` |
| `width` | wave size, integer ≥ 1 | `3` |
| `worktree` | `true`, `false` — the run goes in its own worktree on the branch `bmad/<target>` and is merged later by `auto-bmad land` ([Running](running.md#run-in-its-own-worktree)); `--worktree` / `--no-worktree` win | `false` |
| `triage_subagent` | `true`, `false` — triage of review findings in the `bmad-triager` subagent (fact I, [Under the hood](engine.md#the-facts)) | `false` |

These tool-wide settings apply to native Codex and Claude Code through the same `[run]`.
`conservative` separates dependent stories, shared files/modules or assembly points, and unclear scope.
`aggressive` permits overlapping files but still separates explicit dependencies and shared assembly points.
`off` runs stories one by one. Width is a maximum, not a requirement to fill every wave.

An invalid value is ignored and the built-in default is used.

## `[project_tests]`: project-defined components

The component selection below describes legacy sessions and direct component-test calls.
New native sessions use integration-full-v1: register development targets and build commands
as described below; scopes/fallback never replace development coverage. The full registered
project-tests command remains the pre-main integration gate. Setup inspects the actual project, proposes component boundaries
and commands, discusses them with the user, previews and saves the agreed configuration.
Component names are arbitrary, including web, API, mobile targets, shared libraries and desktop apps.

```toml
[project_tests]
baseline = true
ignore = ["docs/**", "README.md"]
[project_tests.scopes.ui]
paths = ["ui/**", "contracts/**"]
command = "scripts/check-ui.sh"
[project_tests.scopes.service]
paths = ["service/**", "contracts/**"]
command = "scripts/check-service.sh"
[project_tests.fallback]
command = "scripts/check-all.sh"
timeout = 1800
```

Commands are project-specific examples, not universal presets; they must prepare dependencies
in a fresh baseline worktree. Actual committed/uncommitted/new/deleted paths select their components.
Overlapping patterns select both; unknown/shared paths run `fallback` once, or every component
when no fallback is configured. Agreed `ignore` paths affect selection and cache inputs; runtime
`.auto-bmad/` and `_bmad-output/` are ignored by default. Baselines run lazily only for affected components,
against the exact pre-story commit. `baseline=false` disables comparison, not current-code checks.
Component caches retain results across unrelated changes; shared inputs invalidate them. Other
command/agent checks and their level policies remain active.

Optional `[project_tests]` fields provide conservative escalation:
`full_paths = ["contracts/**", "frontend/package*.json", "_bmad-output/**/DESIGN.md"]`
forces the fallback even for a component-owned or ignored path. `full_on_multiple = true`
uses the fallback for changes across multiple components. Without a fallback, every scope runs.
`full_patterns` contains Python regexes over added/deleted diff lines and untracked file contents;
for example `full_patterns = ['fetch\s*\(', '/api/']` catches an API call changed inside a UI file.
Files matching these content patterns and `full_paths` are also shared cache inputs.
This is a conservative guard, not complete contract analysis. The story controller must assess
interaction changes and uncertain impact. Run broader configured checks when required.
Use the same original story baseline throughout repairs and final verification.

`setup tests` inspects without execution. `setup tests --plan <json> --write` saves the agreed
strategy, preserves other settings and backs up the old file. Omit `--write` for preview;
use `--layer local` for machine overrides. Native commands use the caller's permissions:

```bash
auto-bmad test --repo /path/to/worktree --base <original-commit> --name project-tests
auto-bmad test --repo /path/to/worktree --base <original-commit> --name project-tests/ui
```

The component plan may continue in the background. `--wait` bounds a caller's wait; repeating
the command joins the same run. `--rerun` refreshes stale results and baselines; a recent result
may still be reused according to the test helper's cache policy. Cached tests do not prove
that external services are currently healthy.

### Development checks and final verification

A separate development check accepts explicit test files/nodes without changing the final gate:

```toml
[project_tests.development.backend]
command = "scripts/check.sh backend"
targets = ["backend/tests/test_*.py"]
timeout = 1800
```

```bash
auto-bmad test --repo /path/to/worktree --name dev/backend --target backend/tests/test_example.py::test_case
```

The configured command must accept repository-relative selectors as trailing positional arguments.
At least one selector is required; targets must match existing allowed files inside the repository.
Shell options and arbitrary host commands are not accepted as selectors.
Fix all known failures before rerunning the failed commands and affected regressions;
an unrelated pass cannot close a failure. Repeat independent review only for extensive/risky
cumulative changes; localized fixes need explicit delegated revalidation. New native
`check --request PLAN.json` stores focused/build evidence required by development completion.
`land --native-session SESSION --story ID ...` runs the full gate on the combined candidate
before main changes; finalization reuses valid exact-tree/config/command/evidence results.
Legacy journals retain their original final-check contract.

Register fixed compile/build commands alongside development checks:

```toml
[project_tests.build.compile]
command = "scripts/compile.sh"
timeout = 900
```

Use commands that exist in the actual project. `setup tests` reports mappings and gaps and
`setup tests --plan FILE --write` saves the agreed development/build configuration with a
backup. Missing focused targets never trigger automatic full fallback. No build step requires
an explicit `build_not_applicable` reason in the development request. New native setup and
development do not execute full baselines. Early full tests require a concrete broad-risk
reason; after a failed full gate, real focused tests/build must pass before the next full run.

## `[roles.*]`

Legacy Claude overrides per semantic subagent. Prefer the client namespaces
`[executors.claude.roles.<id>]` and `[executors.codex.roles.<id>]` for new settings.
An empty config keeps the client defaults in the [models table](levels.md#models).

```toml
[roles.implementer]
model = "sonnet"
effort = "high"

[roles.edge-case-hunter]
effort = "high"

[roles.story-runner]
model = "opus[1m]"   # Opus with a 1M context; plain "opus" is the regular context
effort = "high"
```

| Key | Values |
|---|---|
| `model` | `sonnet`, `opus`, `opus[1m]`, `haiku`, `fable`, `default` |
| `effort` | `low`, `medium`, `high`, `xhigh`, `max`, `default` |
| `provider` | only `anthropic`; another provider is not supported yet |

Subagents: `story-runner`, `implementer`, `context-compiler`, `blind-hunter`,
`edge-case-hunter`, `intent-alignment`, `verification-gap`, `triager`, `verifier`.
Each review layer has independent model/effort settings. The orchestrator is the main chat:
you pick its model in the host; it is not in this config. Unknown layer IDs require explicit
adapter support and must not fall back to another reviewer.

How it works. The value reaches the subagent as the `model` and `effort` parameters of the
`Agent` call. They win over the agent type's model and effort. The skill passes them for
story-runner and verifier; for the other roles the engine passes them, following the level
profile (facts E, G and I). An agent file in `.claude/agents/` does not work for this: Claude
Code reads agent types once, at session start.

Limits:

- **For Opus with a 1M context, write `model = "opus[1m]"`.** Plain `opus` gives the regular
  context; preflight warns about it. `opus[1m]` is available only to the roles whose agent
  type has it: story-runner and implementer. The `Agent` call cannot pass `[1m]`, so
  `opus[1m]` keeps the agent type's model; for any other role it is a preflight error.
- The other `model` values are aliases from the list.
- `default` (or the default value itself, such as `opus[1m]`) clears an override from a lower
  layer: a project can return a role to its agent type that the personal config changed.
- An invalid value or an unknown `provider` — preflight stops the run. An unknown role or
  key — a warning, the key is not applied.
- `auto-bmad stats show` shows which model actually ran in each role, in the
  "Output by role" line.

To see the result of the layer merge: `auto-bmad roles --repo .`.

## Migrating old role names

Old model-tier keys are read only for compatibility; setup writes semantic subagent IDs.
Migration preserves the resolved model and effort for every role and level, including
explicit per-level overrides:

| Old key | Semantic subagents that inherit it |
|---|---|
| `reviewer-lite` | `intent-alignment` on fast/normal |
| `reviewer-mid` | `blind-hunter`, `edge-case-hunter`, `verification-gap` on fast/normal |
| `reviewer` | all four review layers on deep |
| `compiler-lite` | `context-compiler` |

Inactive layers remain disabled by their level. A semantic role's explicit setting takes
precedence over a legacy alias. The aliases are not launchable subagents; a layer always
launches under its own semantic ID. Inspect the resolved roles and the exact setup backup
before accepting a migration. Do not drop distinct legacy values by replacing them with
one common review model.
Setup migrates the selected file only. If converting it would override a higher layer's
legacy settings, setup refuses to write; migrate that higher layer first (usually
`--layer local`), then retry the lower layer. Inherited files remain untouched.

## `[repair_limits]`

Independent per-story budgets, identical on fast, normal and deep:

```toml
[repair_limits]
spec = 2
review = 5
tests = 10
no_progress = 3
```

`spec` counts actual plan/spec corrections (`bad_spec`); `review` counts review patches
and agent-verifier findings; `tests` counts repairs of failed command checks. Test repairs
never spend the other budgets. One cycle is a batch, not one finding. Counters persist
across follow-up agents and controller passes within the same run. Native journal resume preserves
the counters and baseline; it cannot silently grant a fresh budget. The Claude adapter retains
its established story/baseline counters. Stopped runs do not resume automatically.

`no_progress` limits consecutive test repairs without progress. Progress means the same
check passes or its known failing-test ID set strictly shrinks (`FAILED <id>` or
`FAIL:/ERROR: <id>` lines). Different error text, edited code or unknown output alone
proves no improvement; unknown formats reset the streak on a passing check or host-verified
exact scoped baseline equivalence. Arbitrary skipped checks do not qualify.
The native journal uses recorded `check` evidence and `repair` events. The retained Claude
adapter uses `verify attempt`/`verify observe`.
A plain test rerun does not spend a repair attempt; after a declared repair, an unchanged
red result (including a cached one) counts as no progress.

Fix all known test failures in one batch, then rerun the failed commands and affected
regressions. Repeat independent review only after extensive/risky cumulative changes;
localized fixes need explicit orchestrator revalidation of prior coverage. Initial
independent review and configured final checks remain required. Never disable tests or weaken expectations to get green.
Environment/access failures are not code fixes; recognized environment failures during
retest refund the pending test attempt. Exhaustion or no progress preserves work and blocks.

Budgets must be nonnegative integers; zero disables the category, not its limit.
`no_progress` must be positive. Unknown keys are rejected. The table merges by key across
all four config layers; changes require a newly prepared run. Replace the former
`repair_limits.fast/normal/deep` keys with the categories above.

## `[verify_limits]` (deprecated)

No longer controls repairs; its presence emits a warning. Move the desired budget to
`repair_limits.tests` or `repair_limits.review`. Select checks with `[[verify]].levels`.

## `[[verify]]`

A check after a story. Full field list and examples — [Checks](checks.md#fields-of-a-verify-block).

| Field | Short meaning |
|---|---|
| `name` | identifier, merge key |
| `kind` | `command` or `agent` (default `agent`) |
| `levels` | default `["normal", "deep"]` |
| `command` | shell command for `kind = "command"`; `@test_command` — detected test command |
| `detect` | command deciding if the check applies to the story diff |
| `requires`, `install_hint` | skill the check needs, and how to install it |
| `preflight` | command run by preflight before the run; gets the check fields as JSON on stdin; exit 1 — warning, 2 — blocking |
| `instructions` | markdown for the agent |
| `on_fail` | `fix` (default) or `note` |
| `timeout` | seconds for `kind = "command"`, default 1800 |
| `enabled` | `false` turns it off |
| other fields | passed to the agent as project fields |

## `[[hook]]`

A command called on run events. Details — [Hooks](hooks.md).

| Field | Meaning |
|---|---|
| `name` | identifier, merge key |
| `events` | list of events, for example `["story-done", "story-blocked", "run-end"]` |
| `command` | shell command, run through `sh -c` from the project root |
| `timeout` | seconds, default 120 |
| `enabled` | `false` turns it off |

## Example: Android project

`.auto-bmad.toml`:

```toml
# Run defaults: flags of the command win.
[run]
level = "normal"            # fast | normal | deep
parallel = "conservative"   # conservative | aggressive | off
width = 3                   # stories per wave

# A larger independent test-repair budget.
[repair_limits]
tests = 15

# Unit tests instead of the detected "./gradlew test".
[[verify]]
name = "project-tests"
command = "./gradlew :app:testDebugUnitTest"
timeout = 2400

# Feature check on an emulator through adbm (runs only for UI stories).
[[verify]]
name = "adbm"
build = "./gradlew :app:assembleDebug"
apk = "app/build/outputs/apk/debug/app-debug.apk"
package = "com.example.app"
apis = [35]
notes = "The app sets FLAG_SECURE: turn off screenshot protection in its settings before taking frames."
# serial = "<device serial>"   # allow a physical device; without it, emulators only
# bug_before_after = false     # no before/after builds for bug fixes

# Web: a browser check through mockmatch (runs only for web UI stories), against the design.
[[verify]]
name = "mockmatch"
serve = "npm run dev"
url = "http://localhost:5173"
design_project = "https://claude.ai/design/p/<id>?file=Home.dc.html"   # pulled fresh for each check
# design_artifact = "https://claude.ai/artifact/<id>"   # a claude.ai Design artifact; needs design
design = "design/home.html"      # fallback without the Claude Design login; an HTML mockup or a PNG works too
widths = [1440, 390]

# Static analysis; problems are reported, not fixed.
[[verify]]
name = "lint"
kind = "command"
command = "./gradlew :app:lintDebug"
on_fail = "note"
timeout = 1200

# A project hook: posts a line after each story.
[[hook]]
name = "notify"
events = ["story-done", "story-blocked", "run-end"]
command = "python3 tools/auto-bmad-notify.py"
timeout = 60
```

## Example: Python project

`.auto-bmad.toml`:

```toml
[run]
level = "normal"
parallel = "off"            # one story at a time

# Tests through uv instead of the detected "pytest".
[[verify]]
name = "project-tests"
command = "uv run pytest -q"
timeout = 900

# Type check; the engine fixes problems, up to the level's limit.
[[verify]]
name = "types"
kind = "command"
command = "uv run mypy src"
on_fail = "fix"
timeout = 600
```

The `adbm` check needs no entry here: it applies only to projects with
`settings.gradle(.kts)`. Neither does `mockmatch`: it applies only to stories that touch
the web UI.

## Example: personal config

`~/.config/auto-bmad/config.toml`:

```toml
# Prefer deep reviews on this machine unless a project or a flag says otherwise.
[run]
level = "deep"

# Blind Hunter with the most effort; a project can return it with effort = "default".
[roles.blind-hunter]
effort = "max"

[[hook]]
name = "desktop-notify"
events = ["story-blocked", "run-end"]
command = "python3 ~/.config/auto-bmad/hooks/notify.py"
timeout = 30
```

A project's `.auto-bmad.toml` wins over this file.

## Files auto-bmad creates in a project

| Path | What | In git |
|---|---|---|
| `.auto-bmad.toml` | project config (written by setup) | commit it |
| `.claude/auto-bmad-headless.json` | permissions for unattended runs (written by setup) | commit it |
| `_bmad/custom/bmad-build-auto.user.toml` | level profile, rewritten each run | excluded locally via `.git/info/exclude` |
| `.auto-bmad/` | events journal, statistics, check state | excluded locally via `.git/info/exclude` |
| `.claude/worktrees/` | worktrees of parallel stories and of worktree runs (`bmad-<target>`) | excluded locally via `.git/info/exclude` |
| `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md` | open questions of an epic | committed by the run |

## Local epic landing

```toml
[execution]
backend = "native"
merge_policy = "auto-main" # default: "manual"
```

For Codex, the main chat completes all stories and tracking, then integrates the verified epic
into local `main`. Main must be checked out in a local worktree. If main advances, integrate
its changes into the run branch and rerun affected checks. Conflicts, unfinished checks or
unrelated edits preserve the work and produce a concrete blocker. Editorial questions alone
do not prevent landing. Single-story runs do not land automatically. Push and deployment are separate.
The native journal records verification/finalization; the chat reports actual landing status.

## Bounded checkpoint compatibility

New native journals save `checkpoint_policy="bounded-checkpoints-v1"`; this is a
session protocol, not a user model setting. Missing policy preserves old semantics.
Local attempts and diagnostics each have a fixed maximum of 3 per admitted batch;
existing story/no-progress limits can stop earlier and never reset on resume.
Development/build entries optionally accept boolean `independent` (default false).
Do not migrate active journals or replace pinned packages. Models and Claude settings
are unchanged. See [protocol](../../skills/auto-bmad/CHECKPOINTS.md).

For bounded-checkpoints-v1, older `land --native-session` examples additionally
require `--native-task TASK`: stage the full gate, complete/accept that task receipt,
then dispatch a fresh integration task to land using the accepted exact-candidate gate.
The single-call examples remain valid only for the legacy session policy.
