# Configuration

[Русский](../ru/config.md) · [Back to README](../../README.md)

## Three layers

auto-bmad reads three TOML files. Each next layer wins over the previous one.

| Layer | File | For |
|---|---|---|
| defaults | `defaults.toml` in the plugin | built-in checks and limits; do not edit |
| personal | `~/.config/auto-bmad/config.toml`, or the file in `$AUTO_BMAD_CONFIG` | your own hooks and preferences on this machine |
| project | `.auto-bmad.toml` in the repository root | project settings; commit it |

Merge rules:

- Tables (`[run]`, `[verify_limits]`) merge by key.
- Arrays of tables `[[verify]]` and `[[hook]]` merge by the `name` field: a block with the
  same `name` adds and overrides fields; a new `name` adds a new block.
- `enabled = false` turns a hook or check off.
- Any other value (including plain arrays such as `apis`) is replaced.
- A layer that cannot be read is skipped with a warning; the run goes on.

See the merged result and which files were used:

```bash
auto-bmad ext config --repo .
```

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

An invalid value is ignored and the built-in default is used.

## `[roles.*]`

Model and effort per role. An empty config — every role keeps the model and effort of its
agent type, as in the [models table](levels.md#models).

```toml
[roles.implementer]
model = "sonnet"
effort = "high"

[roles.reviewer-mid]
effort = "high"
```

| Key | Values |
|---|---|
| `model` | `sonnet`, `opus`, `haiku`, `fable`, `default` |
| `effort` | `low`, `medium`, `high`, `xhigh`, `max`, `default` |
| `provider` | only `anthropic`; another provider is not supported yet |

Roles: `story-runner`, `implementer`, `reviewer`, `reviewer-mid`, `reviewer-lite`,
`compiler-lite`, `verifier`. The orchestrator is the main session: you pick its model, it is
not in the config.

How it works. The value reaches the subagent as the `model` and `effort` parameters of the
`Agent` call. They win over the agent type's model and effort. The skill passes them for
story-runner and verifier; for the other roles the engine passes them, following the level
profile (facts E and G). An agent file in `.claude/agents/` does not work for this: Claude
Code reads agent types once, at session start.

Limits:

- `model` is only an alias from the list. Story-runner and implementer default to Opus
  with a 1M context. The override `model = "opus"` gives Opus with the regular context;
  preflight warns about it.
- `default` (or the default value itself, such as `opus[1m]`) clears an override from a lower
  layer: a project can return a role to its agent type that the personal config changed.
- An invalid value or an unknown `provider` — preflight stops the run. An unknown role or
  key — a warning, the key is not applied.
- `auto-bmad stats show` shows which model actually ran in each role, in the
  "Output by role" line.

To see the result of the layer merge: `auto-bmad roles --repo .`.

## `[verify_limits]`

Fixes per story after checks, by level. See [Checks](checks.md#the-fix-loop).

```toml
[verify_limits]
fast = 0
normal = 2
deep = 3
```

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

# One more fix than the default on normal.
[verify_limits]
normal = 3

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
| `.claude/worktrees/` | worktrees of parallel stories | excluded locally via `.git/info/exclude` |
| `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md` | open questions of an epic | committed by the run |
