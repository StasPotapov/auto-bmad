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
- In an already configured project, offer local settings for personal model/effort changes or a
  machine-only agent addition. Recommend local overrides for personal changes; change shared defaults
  when the user wants the change for the project. Ask the storage choice only when it is still unclear;
  reuse an explicit choice from the conversation. Existing complete settings need no mandatory change
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
| Codex | Work/controller/compiler/triager/verifier: `gpt-6.1-sol`, high. All reviewers: `gpt-6-astra`, high, read-only. |
| Native Claude | Controller/implementation: Opus 1M, medium. Review roles: Haiku/high and Sonnet/medium or high. Compiler: Haiku/high; verifier: Sonnet/medium; triager: Opus/high. |

Read Codex values from `agents/codex-defaults.toml` and Claude values from `agents/bmad-*.md`
in the source package; project/local values may differ. Do not equate a review role to an entire level:
levels select review layers, and a level can use several review roles.
Offer three simple choices when model customization is wanted: built-in defaults; shared models for
all levels; or differences for `fast`, `normal`, and `deep`. These choices are independent of project/local storage.
For Codex, explain the compact format: `[executors.codex]` sets common values;
`[executors.codex.levels.fast|normal|deep]` sets only differences. Missing values inherit the common
settings and built-in defaults. Optional `.roles.<role>` tables override one role. The native Claude
workflow retains its `[roles.*]` overrides; do not invent compact Claude level commands.

Then follow the setup steps below. Showing this choice does not add a separate approval step after
the user has already chosen the settings and storage scope.

## Setup steps

1. Run `<setup> check --repo <project>`. It never starts models or hooks. `agents` lists the available
   choices; `execution` reports the current backend, CLI interface checks and engine blockers.
   The frontend identifies the current host: Codex uses Codex CLI, native Claude uses its native plugin.
   Do not ask to switch the project or choose an executor when the host is already known. Add the current
   host's missing settings while keeping the stored default; `execution.configured_backend` shows that
   default separately from the effective backend. Ask the executor only for a standalone/unknown host.
   Kimi and Claude CLI execution are unavailable;
   do not present them as runnable or silently substitute another executor.
2. Handle missing environment, BMAD engine and planning first. Setup needs git, Python 3.11+ and uv.
   The engine contract still reads `.claude/skills/bmad-build-auto` and `_bmad/scripts/` even when
   Codex is the executor; these are workflow files, not a dependency on a running Claude CLI.
   If BMAD is absent, offer the reported install/update command and let the user choose who runs it.
   Do not install packages under setup authorization alone. Planning remains a conversation:
   PRD → architecture → epics → sprint planning (`sprint-status.yaml`). Do not invent product requirements.
3. One TOML stores both executors: native Claude settings in `[roles.*]`, compact Codex settings
   in `[executors.codex]`, and shared project checks/hooks/run settings. Older `[agents.*]`/`[routing.*]`
   remain supported. Runtime selection follows the current host and never edits `[execution].backend`.
   First preview `<setup> agent --agent codex --add --repo <project>` without model options.
   Existing complete settings are reused; new Codex settings use built-in defaults (`defaults_used=true`).
   Show `resolved_roles` for compact settings; do not ask the user to fill model IDs again just to use defaults.
   To customize, collect exact IDs and effort; never translate Claude aliases. Compact `model`/`effort`
   configure work roles, `review_model`/`review_effort` configure reviewers independently.
   Use `agent --level fast|normal|deep` for one compact level, omitting `--level` for common values.
   Native Claude uses its role command. Keep older advanced configs unchanged unless the person wants
   compaction: preview `agent --agent codex --compact --add` and show its backup/file change before writing.
   Conversion preserves every role's model, effort and environment at every level; unsupported advanced
   profiles are refused. `--advanced` is an explicit escape hatch for manual profiles/routes.
   Add environment variable **names**, not values, through repeated `--env` when needed.
4. Epics run sequentially. Preserve existing command and agent checks, including mockmatch,
   adbm and custom verifiers. CLI checks use the configured `verifier` role and the skills installed
   for Codex; a missing skill or external service is reported as skipped with a reason. Never ask
   to disable these checks just to select Codex. `--disable-agent-checks` is an optional opt-out
   only when the user explicitly requests command checks alone. Previously disabled checks remain
   disabled; offer to re-enable the named checks when the user wants them back. Existing test commands
   and hooks stay unchanged. Missing test command in a new project: ask and pass `--test-command`.
5. Preview the selected configuration, with no `--write`:

   New Codex project:

   ```text
   <setup> init --repo <project> --agent codex --parallel off --test-command <command>
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

   Only an explicit request to change the standalone default uses `--select`. New `init` creates the
   initial default for the current host; there is no existing executor to switch.
   For Claude settings use `--agent claude --add`, with no CLI model options. A missing project config
   uses `init` and the native setup's level/test/UI decisions. Existing projects use `agent`:
   it preserves old Claude model/effort settings. The native Claude setup is at `SKILL.md` next
   to this file; its legacy environment-specific extras apply only in Claude Code. In Codex,
   configuring the native backend does not make it executable in this chat.

   Show the executor, model/effort, affected file, and checks disabled. After collecting these
   choices, execute the same command with `--write`; the request to set up the project authorizes
   writing the chosen settings. Do not add another approval loop. Never use `init --force` to migrate.
6. Agent configuration is merged from defaults → personal → project → local. The shared `.auto-bmad.toml`
   is the project's versioned default. Use `--layer local` for machine-only additions or overrides in
   `.auto-bmad.local.toml`; the helper excludes it from Git and refuses to edit it if already tracked.
   Ask the storage scope only when the person's request does not make it clear; default to project settings
   for a shared project setup and to local for explicitly personal/machine-specific changes.
   For native Claude model/effort overrides use `role --layer local --role <role> --model <alias>`
   through the native frontend (or explicit `--executor claude`); it also excludes the local file and makes a backup.
   Setup validates all layers before writing. A conflicting local model/profile override must not silently defeat the requested
   settings: report it and offer `agent --layer local`. Do not rewrite the personal config.
   Explicit `--agent claude` also masks inherited CLI routes without deleting the lower layer;
   native model/effort overrides still apply. A default backend with unselected CLI settings remains an error.
   Each changed existing file gets an exact backup under `.auto-bmad/setup-backups/`; unrelated
   TOML settings are retained, and an unchanged selection makes no new backup. Local selections are excluded from git. Switching
   back to native Claude does not automatically re-enable checks previously disabled for CLI.
7. Run `check` again. No model is called: interface compatibility is not a live inference test.
   Distinguish configuration written from project ready. Report remaining BMAD/planning/CLI blockers.
   Do not call a project ready with `ready: false`. In Codex, a native Claude backend still needs
   Claude Code to run. For a ready Codex project show `$auto-bmad 1-1` / `$auto-bmad epic-1 --normal`.
   For Claude show `/auto-bmad:auto-bmad 1-1`. A separate execution request starts the actual run.

`headless` returns a shared CLI command for CLI projects and writes no Claude permissions file.
Native Claude projects retain the previous headless/settings workflow. Setup does not run tests,
hooks, commit, merge or push automatically; committing the project config is a separate action.
