# Shared setup: executor and project configuration

Use the user's language. The chat collects choices; the shared CLI validates and writes TOML.
In Codex use this skill's `scripts/setup.py` helper. In the Claude plugin use `auto-bmad setup`
(or the plugin's absolute `bin/auto-bmad setup` path). Replace `<setup>` below with that command.

1. Run `<setup> check --repo <project>`. It never starts models or hooks. `agents` lists the available
   choices; `execution` reports the current backend, CLI interface checks and engine blockers.
   Preserve a configured executor unless the user asks to change it. For a new project ask:
   **Codex CLI** (shared CLI, isolated story/sequential epic) or **Claude Code native plugin**
   (existing workflow, including native parallel waves). Kimi and Claude CLI execution are unavailable;
   do not present them as runnable or silently substitute another executor.
2. Handle missing environment, BMAD engine and planning first. Setup needs git, Python 3.11+ and uv.
   The engine contract still reads `.claude/skills/bmad-build-auto` and `_bmad/scripts/` even when
   Codex is the executor; these are workflow files, not a dependency on a running Claude CLI.
   If BMAD is absent, offer the reported install/update command and let the user choose who runs it.
   Do not install packages under setup authorization alone. Planning remains a conversation:
   PRD → architecture → epics → sprint planning (`sprint-status.yaml`). Do not invent product requirements.
3. For Codex collect an exact model ID and effort. Reuse an explicit choice in this conversation;
   otherwise ask rather than translating Claude aliases or guessing a model. The write/controller and
   review profiles may use different models (`--review-model`, `--review-effort`); by default review
   uses the selected model/effort, with enforced read-only permissions. `--executable` selects the
   installed CLI path. Add build environment variable **names** with repeated `--env` if needed;
   never put secret values into TOML or a report.
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
   <setup> init --repo <project> --agent codex --model <id> --effort <effort> --parallel off --test-command <command>
   ```

   Existing project (or reconfigure profiles):

   ```text
   <setup> agent --repo <project> --agent codex --model <id> --effort <effort>
   ```

   For Claude selection use `--agent claude`, with no CLI model options. A missing project config
   uses `init` and the native setup's level/test/UI decisions. Existing projects use `agent`:
   it preserves old Claude model/effort settings. The native Claude setup is at `SKILL.md` next
   to this file; its legacy environment-specific extras apply only in Claude Code. In Codex,
   configuring the native backend does not make it executable in this chat.

   Show the executor, model/effort, affected file, and checks disabled. After collecting these
   choices, execute the same command with `--write`; the request to set up the project authorizes
   writing the chosen settings. Do not add another approval loop. Never use `init --force` to migrate.
6. Agent configuration is merged from defaults → personal → project → local. Setup validates all
   three levels after merging before writing. A local override must not silently defeat the chosen
   executor: report it and offer `agent --layer local` to keep that
   choice on this machine. Do not rewrite the personal config.
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
