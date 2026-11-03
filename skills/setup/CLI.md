# Shared setup: executor and project configuration

Use the user's language. The chat collects choices; the shared CLI validates and writes TOML.
In Codex use this skill's `scripts/setup.py` helper. In the Claude plugin use `auto-bmad setup`
(or the plugin's absolute `bin/auto-bmad --executor claude setup` path). Replace `<setup>` below with that command.

## Explain the existing setup

After `check`, before proposing changes, explain the findings in the user's language:

- Name the settings that already exist and whether the current agent's profiles are complete.
  If profiles are missing, say that setup will add only the current agent's settings while preserving
  the other agents and shared checks. If they are complete, offer to use the saved settings.
- Explain that `.auto-bmad.toml` holds shared project defaults that can be committed with the project.
  `.auto-bmad.local.toml` holds additions and overrides for this computer, takes precedence over the
  project file, and is excluded from Git by setup.
- Client model/effort settings default to private `.auto-bmad.local.toml`, under
  `[executors.codex]` or `[executors.claude]`. Preserve the other client namespace.
  Change shared defaults only when explicitly requested with `--layer project`.
  Reuse an explicit storage choice from the conversation. Existing complete settings need no mandatory change
  or extra question: explain the local option and continue with them.

For example, when Codex settings are missing: “В проекте уже есть настройки Claude Code.
Добавлю только настройки Codex. Общие настройки хранятся в `.auto-bmad.toml` и могут попасть в коммит.
Для этого компьютера можно добавить `.auto-bmad.local.toml`: он перекроет проектные значения и останется вне Git.”
When the current agent is already configured: “Для Codex уже сохранены модели и effort; можно использовать их.
Если хотите другие значения только на этом компьютере, настрою локальный файл.”
Adapt the example to the observed files and current agent; do not claim settings exist without checking.

Both executors have built-in models. Show a short summary before asking for custom values:

| Executor | Built-in models |
|---|---|
| Codex | Work/controller/compiler/triager/verifier: `gpt-6.1-sol`, high. All reviewers: `gpt-6-astra`, high. Reviewers receive a no-edit instruction and inherit chat permissions. |
| Native Claude | Controller/implementation: Opus 1M, medium. Review roles: Haiku/high and Sonnet/medium or high. Compiler: Haiku/high; verifier: Sonnet/medium; triager: Opus/high. |

Read Codex values from `agents/codex-defaults.toml` and Claude values from its native role wrappers in `agents/bmad-*.md`
in the source package; shared role bodies are in `prompts/roles/`; project/local values may differ. Do not equate a review role to an entire level:
levels select review layers, and a level can use several review roles.
Offer three simple choices when model customization is wanted: built-in defaults; shared models for
all levels; or differences for `fast`, `normal`, and `deep`. These choices are independent of project/local storage.
For Codex, explain the compact format: `[executors.codex]` sets common values;
`[executors.codex.levels.fast|normal|deep]` sets only differences. Missing values inherit the common
settings and built-in defaults. Optional `.roles.<role>` tables override one role. Claude uses its own `[executors.claude]` namespace with common, level and role overrides.
Legacy `[roles.*]` remains a fallback. Never translate one client's model names into another's.

Then follow the setup steps below. Showing this choice does not add a separate approval step after
the user has already chosen the settings and storage scope.

## Project test strategy (all executors)

After `check`, run `<setup> tests --repo <project>` before writing settings, including on an
already configured project. It reads manifests and saved settings without tests, models or hooks.
Inspect the reported components, package scripts, project check scripts and project instructions.
Do not assume a frontend/backend split: the project may contain mobile targets, a service, shared
modules, a desktop app, or one inseparable component. Detected commands are evidence/candidates,
not a validated strategy; read their scripts and dependencies before recommending them.

Show a small proposed table: component, changed paths, checks/command, dependencies it needs.
Discuss it with the user: boundaries and overlaps, shared configuration/contracts, documentation
that does not require product tests, and whether to keep baseline comparison (recommended).
Explain when checks run: on actual changes to that component; any unknown/shared product path
runs the configured fallback once, or all components without one; edits to declared shared paths can select several. Both parts changed means
both suites. Existing command/agent verifiers and their level policies remain in effect.
Commands must prepare their prerequisites in a fresh exact-base worktree; do not assume a venv,
node_modules or device state already exists. Keep device/emulator verification separate from unit tests.
Never save one universal web/mobile template without discussing the actual project.

Use one common `[project_tests]` strategy for every executor. Save the agreed table as a temporary
JSON object with `baseline` (boolean, default true), `ignore` (relative path patterns) and `scopes`:
each named scope has `paths`, `command` and optional positive `timeout` seconds. Names are arbitrary.
Optional `fallback` has a command and timeout: it runs once for unknown/shared paths, including
project-wide checks that individual component commands omit. Without it every component runs.
Preview `<setup> tests --repo <project> --plan <json-path> [--layer project|local]`, show the resolved
configuration, then repeat with `--write` once the user has chosen the strategy and storage layer.
There is no extra approval after those choices. The helper backs up existing files and preserves
models, other checks, hooks and run settings; a conflicting config layer is reported instead of ignored.
Missing or uncertain commands remain questions for the user; setup never runs them to guess.

## Setup steps

1. Run `<setup> check --repo <project>`. It never starts models or hooks. `agents` lists the available
   choices; `execution` reports the current backend, model settings and engine blockers.
   The frontend identifies the current host: Codex uses native collaboration tools, native Claude uses its native plugin.
   Do not ask to switch the project or choose an executor when the host is already known. Add the current
   host's missing settings while keeping the stored default; `execution.configured_backend` shows that
   default separately from the effective backend. Ask the executor only for a standalone/unknown host.
   The former Codex CLI backend is removed. Old `backend="cli"` settings resolve to native with a migration warning.
   Missing native tools cannot be replaced by an executable or another executor.
2. Handle missing environment, BMAD engine and planning first. Setup needs git, Python 3.11+ and uv.
   The engine contract still reads `.claude/skills/bmad-build-auto` and `_bmad/scripts/` even when
   Codex is the executor; these are workflow files, not a dependency on a running Claude CLI.
   If BMAD is absent, offer the reported install/update command and let the user choose who runs it.
   Do not install packages under setup authorization alone. Planning remains a conversation:
   PRD → architecture → epics → sprint planning (`sprint-status.yaml`). Do not invent product requirements.
3. Shared project TOML stores checks, hooks and run settings. Private client model settings
   default to `[executors.codex]` and `[executors.claude]` in `.auto-bmad.local.toml`.
   Legacy Claude `[roles.*]` remains supported as a fallback. Older `[agents.*]`/`[routing.*]`
   remain supported. Runtime selection follows the current host and never edits `[execution].backend`.
   First preview `<setup> agent --agent codex --add --repo <project>` without model options.
   Existing complete settings are reused; new Codex settings use built-in defaults (`defaults_used=true`).
   Show `resolved_roles` for compact settings; do not ask the user to fill model IDs again just to use defaults.
   To customize, collect exact IDs and effort; never translate Claude aliases. Compact `model`/`effort`
   configure work roles, `review_model`/`review_effort` configure reviewers independently.
   Use `agent --level fast|normal|deep` for one level, omitting `--level` for common values.
   Use `--role <role>` with model/effort to change one role in either client namespace.
   Claude uses its own namespace and native role values. Keep older advanced configs unchanged unless the person wants
   compaction: preview `agent --agent codex --compact --add` and show its backup/file change before writing.
   Conversion preserves every role's model and effort at every level; unsupported adapters or incomplete routes
   are refused. Executable, environment and timeout transport fields are inactive in native mode. `--advanced` is an explicit escape hatch for manual profiles/routes.
   Do not set `--executable`, `--env`, or `--timeout` for native Codex; setup rejects these obsolete transport options.
4. Epics use shared `[run].parallel`/`width` settings: conservative waves by default, with one
   isolated worktree per concurrent story. Preserve existing command and agent checks, including mockmatch,
   adbm and custom verifiers. Native agent checks use the configured `verifier` role and the skills installed
   for Codex; a missing skill or external service is reported as skipped with a reason. Never ask
   to disable these checks just to select Codex. `--disable-agent-checks` is an optional opt-out
   only when the user explicitly requests command checks alone. Previously disabled checks remain
   disabled; offer to re-enable the named checks when the user wants them back. Existing test commands
   and hooks stay unchanged. Missing test command in a new project: ask and pass `--test-command`.
5. Preview the selected configuration, with no `--write`:

   New Codex project:

   ```text
   <setup> init --repo <project> --parallel off --test-command <command>
   <setup> agent --repo <project> --agent codex --add --layer local
   ```

   Existing project (or reconfigure profiles):

   ```text
   <setup> agent --repo <project> --agent codex --add --model <id> --effort <effort>
   ```

   Personal override for one compact level (the other levels keep their settings):

   ```text
   <setup> agent --repo <project> --agent codex --add --level deep --review-model <id> --layer local
   ```

   Add/check saved settings or built-in defaults without changing the standalone default:

   ```text
   <setup> agent --repo <project> --agent claude --add
   <setup> agent --repo <project> --agent codex --add
   ```

   Only an explicit request to change the standalone default uses `--select`.
   Prefer `init` for common project settings, then `agent` for private client settings.
   The legacy explicit `init --agent` convenience remains available but is not required.
   For Claude settings use `--agent claude --add` and exact native model/effort values when requested. A missing project config
   uses `init` and the native setup's level/test/UI decisions. Existing projects use `agent`:
   it preserves old Claude model/effort settings. The native Claude setup is at `SKILL.md` next
   to this file; its legacy environment-specific extras apply only in Claude Code. In Codex,
   configuring Claude does not make its Agent tools available in Codex.

   Show the executor, model/effort, affected file, and checks disabled. After collecting these
   choices, execute the same command with `--write`; the request to set up the project authorizes
   writing the chosen settings. Do not add another approval loop. Never use `init --force` to migrate.
6. Agent configuration is merged from defaults → personal → project → local. The shared `.auto-bmad.toml`
   is the project's versioned default. Use `--layer local` for machine-only additions or overrides in
   `.auto-bmad.local.toml`; the helper excludes it from Git and refuses to edit it if already tracked.
   Keep client settings private by default. Write shared model settings only when explicitly requested.
   The frontend identifies the current client; a standalone unknown host must choose one.
   For native Claude model/effort overrides prefer `agent --agent claude --role <role> --model <alias>`.
   The legacy `role` command remains a compatibility path; the client namespace takes precedence.
   Setup validates all layers before writing. A conflicting local model/profile override must not silently defeat the requested
   settings: report it and offer `agent --layer local`. Do not rewrite the personal config.
   Explicit `--agent claude` also masks inherited CLI routes without deleting the lower layer;
   native model/effort overrides still apply. Unsupported or incomplete inherited role routes remain an error.
   Each changed existing file gets an exact backup under `.auto-bmad/setup-backups/`; unrelated
   TOML settings are retained, and an unchanged selection makes no new backup. Local selections are excluded from git. Switching
   to Claude does not automatically re-enable previously disabled checks.
7. Run `check` again. No model is called. Configuration validation does not prove native-tool availability or a successful story.
   Inspect the current chat's collaboration tools separately. Report remaining BMAD/planning/native-tool blockers.
   Do not call a project ready with `ready: false`. In Codex, a native Claude backend still needs
   Claude Code to run. For a ready Codex project show `$auto-bmad 1-1` / `$auto-bmad epic-1 --normal`.
   For Claude show `/auto-bmad:auto-bmad 1-1`. A separate execution request starts the actual run.

`headless` refuses native Codex execution: an active chat must orchestrate native agents.
Native Claude projects retain their headless/settings workflow. Setup does not run tests,
hooks, commit, merge or push automatically; committing the project config is a separate action.

The core lifecycle, role prompts, checks and project configuration are shared. Client adapters own
native tool mappings, model names, effort and private settings. AI Workspace can install/update the
package; the runtime requires neither AI Workspace nor its Python modules.
