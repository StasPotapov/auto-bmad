# Install and set up

[Русский](../ru/install.md) · [Back to README](../../README.md)

## Requirements

| What | Why |
|---|---|
| Claude Code | auto-bmad is a Claude Code plugin |
| git | every story ends with a commit; the project must be a git repository |
| uv | BMad renders its `bmad-build-auto` engine through `uv run` |
| Python 3.11+ as `python3` | the `auto-bmad` CLI runs plain-stdlib Python scripts; config parsing needs `tomllib` (3.11+) |
| BMad 6.12+ with the `bmm` module | auto-bmad drives BMad's `bmad-build-auto` engine; it does not replace it |
| `npx` (Node.js) | only to run the BMad installer |
| [adbm](https://github.com/StasPotapov/adbm) plugin | optional; only for checks on an Android emulator |
| [mockmatch](https://github.com/StasPotapov/mockmatch) plugin | optional, recommended for web projects; checks in a headless browser and against the design |

## Install the plugin

The plugin lives in the [sp-tools](https://github.com/StasPotapov/sp-tools) marketplace.
Ask Claude Code to do it ("install the auto-bmad plugin from the StasPotapov/sp-tools
marketplace"), or run the two commands yourself:

```bash
claude plugin marketplace add StasPotapov/sp-tools
claude plugin install auto-bmad@sp-tools
```

Restart Claude Code. The plugin adds:

- the skill `/auto-bmad:auto-bmad` — the run itself;
- the skill `/auto-bmad:setup` — guided setup of a project;
- the subagent types the run needs (`auto-bmad:bmad-story-runner`, reviewers, verifier);
- the `auto-bmad` CLI. While the plugin is enabled, its `bin/` is on the PATH of
  Claude Code's Bash tool. Outside Claude Code, call it by its full path inside the
  plugin's install directory.

For Android checks, also install adbm and restart Claude Code again:

```bash
claude plugin marketplace add StasPotapov/sp-tools
claude plugin install adbm@sp-tools
```

For web checks, install mockmatch, restart Claude Code, then ask the agent to run
`mockmatch doctor --install` (a private venv with Playwright and Chromium):

```bash
claude plugin marketplace add StasPotapov/sp-tools
claude plugin install mockmatch@sp-tools
```

## Set up a project

Open Claude Code in the project folder and run:

```
/auto-bmad:setup
```

The setup skill does the work and asks you only at decision points. It is re-entrant:
when it sends you away (to install something, restart, or plan), come back and run
`/auto-bmad:setup` again. It always starts from the facts:

```bash
auto-bmad setup check --repo .
```

This prints JSON with one block per stage and a `next` field: the first unfinished stage
and what to do. `ready: true` means all required stages are done.

| Block | What it reports |
|---|---|
| `env` | `git`, `uv`, `python` and `python_ok` (3.11+), `npx`, `git_repo` (the folder is a git repository) |
| `bmad` | `installed`, `version`, `version_ok` (6.12+), `engine` (`.claude/skills/bmad-build-auto/SKILL.md` exists), `user_config`, the `install` command; `update` when the version is too old |
| `plan` | `epics` (path to the epics file under `_bmad-output/planning-artifacts/`), `sprint_status` (`_bmad-output/implementation-artifacts/sprint-status.yaml` exists) |
| `project` | `config` (`.auto-bmad.toml` exists), `test_command` (found test command), `android` (detected app module, its build command, APK path, package, other `candidates`), `web` (detected front end: folder, framework, `serve` command, `url`) |
| `extras` | `adbm` (installed; only for Android projects), `mockmatch` (installed; only for web projects), `personal_config` (path of your personal config, if it exists) |
| `headless` | `settings` (path of `.claude/auto-bmad-headless.json`, if it exists) |

### Stage 1 — environment (`env`)

Missing `git`, `uv` or Python 3.11+, or the folder is not a git repository. Setup names
what is missing and the install command (for example `brew install uv`, `git init`).
It does not install system packages. Fix it and run `/auto-bmad:setup` again.

### Stage 2 — BMad (`bmad`)

BMad is missing, older than 6.12, or has no `bmad-build-auto` engine. Setup offers two ways:

- **You run the installer** (recommended — it asks for a name, language and folders):

  ```bash
  cd /path/to/project
  npx bmad-method install
  ```

  Choose the **BMad Method (bmm)** module and the **Claude Code** tool.
- **Setup installs it with defaults:**

  ```bash
  npx bmad-method install --yes --modules bmm --tools claude-code
  ```

To update an old BMad, setup uses:

```bash
npx bmad-method install --yes --action update --modules bmm
```

The update rewrites BMad's own files under `_bmad/` and `.claude/skills/`. Your planning
files in `_bmad-output/` stay. After installing or updating, restart Claude Code: new
BMad skills appear only after a restart.

### Stage 3 — plan (`plan`)

auto-bmad implements stories; it does not invent the product. It needs an epics file
and `sprint-status.yaml`. You make them with BMad's planning skills, in a conversation:

| Step | BMad skill | Result |
|---|---|---|
| Requirements | `bmad-prd` (optionally `bmad-product-brief` first) | PRD |
| Architecture | `bmad-create-architecture` | architecture document |
| Epics and stories | `bmad-create-epics-and-stories` | epics file |
| Sprint planning | `bmad-sprint-planning` | `sprint-status.yaml` |

Not sure where you are — `bmad-help` tells the next step. Setup can start the next
planning skill for you, but it does not fill the plan in on its own.

### Stage 4 — project settings (`project`)

Setup asks up to four questions in one go:

1. **Default level** — `normal` (recommended), `fast` or `deep`. See [Levels](levels.md).
2. **Parallel stories** — `conservative` (recommended), `aggressive` or `off`.
   See [Running](running.md#parallel-waves).
3. **Android app module** — only if the project has more than one app module.
4. **Android checks** — only for Android projects: check each UI story on an emulator
   with adbm, or tests only.
5. **Web checks** — only for web projects: check each UI story in a headless browser
   with mockmatch (recommended), or tests only. Setup shows the detected `serve` and `url`
   and asks you to correct them; if the project has a design file, it offers `design`.
   A project with several Android modules and a web front end gets this question in a second call.

Then it writes `.auto-bmad.toml`:

```bash
auto-bmad setup init --repo . --level normal --parallel conservative --write
```

Other options of `init`:

| Option | Meaning |
|---|---|
| `--width N` | wave size for parallel runs (default 3) |
| `--test-command "<cmd>"` | test command when none was found |
| `--android-module <m>` | which app module to check, when there are several |
| `--no-android` | write `enabled = false` for the `adbm` check |
| `--no-web` | write `enabled = false` for the `mockmatch` check |
| `--force` | overwrite an existing `.auto-bmad.toml` |

Without `--write`, `init` only prints the text. With `--write` and an existing file, it
exits with code 2 and `exists: true`; setup shows you the difference before `--force`.

A generated file for an Android project looks like this:

```toml
[run]
level = "normal"
parallel = "conservative"
width = 3

[[verify]]
name = "project-tests"
command = "./gradlew test"

[[verify]]
name = "adbm"
build = "./gradlew :app:assembleDebug"
apk = "app/build/outputs/apk/debug/app-debug.apk"
package = "com.example.app"
apis = [35]
```

Commit `.auto-bmad.toml`. It belongs in the repository, and an untracked file makes the
working tree dirty — the run stops on a dirty tree.

Settings for this machine only go to `.auto-bmad.local.toml` next to it: it wins over
`.auto-bmad.toml` and stays out of git — `auto-bmad setup local --write` adds it to
`.gitignore`. See [Configuration](config.md#four-layers).

### Stage 5 — optional extras

You can pick any of these, or none:

- **Unattended runs** — writes `.claude/auto-bmad-headless.json`, a permissions file
  for `claude -p`:

  ```bash
  auto-bmad setup headless --repo . --write
  ```

  The output contains the file and a ready `claude -p` command.
  See [Unattended runs](unattended.md). Commit this file too.
- **Hooks** — setup copies `examples/hook-template.py` where you want it and adds a
  `[[hook]]` block to your config. See [Hooks](hooks.md).

### Stage 6 — final check

```bash
auto-bmad preflight --repo .
auto-bmad verify baseline --repo .
```

`preflight` lists anything that would block a run (see [CLI](cli.md#preflight)).
`verify baseline` runs the project tests once. If they already fail, auto-bmad will not
try to fix them during runs.

## Update the plugin

The plugin is installed as a copy in Claude Code's plugin cache, not linked to the
marketplace source. To get a new version:

```bash
claude plugin marketplace update sp-tools
claude plugin update auto-bmad@sp-tools
```

Installed earlier as `auto-bmad@auto-bmad` (the StasPotapov/auto-bmad marketplace)? It still
works. To move to sp-tools: `claude plugin uninstall auto-bmad@auto-bmad`, then the two install
commands above.

Then restart Claude Code. In your own config, refer to plugin files as `@plugin/…`
(see [Configuration](config.md)), not by their cache path: the path changes with the version.

## Run from a local checkout

To try a local copy without installing it:

```bash
claude --plugin-dir /path/to/auto-bmad
```

Tests of the plugin itself:

```bash
python3 -m unittest discover -s tests
claude plugin validate .
```


## Codex and local skill

The source package contains a Codex manifest at `.codex-plugin/plugin.json` and a thin Codex skill
at `integrations/codex/skills/auto-bmad`. Native Claude metadata and skills remain separate; both call
the shared runtime with the Codex executor selected for the invocation. Use the whole plugin checkout, not a copied SKILL.md.

For local development, link the skill folder (do not overwrite an existing skill):

```bash
mkdir -p "$HOME/.agents/skills"
ln -s /absolute/path/to/auto-bmad/integrations/codex/skills/auto-bmad "$HOME/.agents/skills/auto-bmad"
```

If HOME is managed with dotfiles/Stow, put that link in its source package and apply Stow instead.
Codex supports linked skill folders and detects changes; see [official skill discovery](https://learn.chatgpt.com/docs/build-skills).
The helper resolves the link back to the plugin's shared scripts, so no global PATH shim is required.
Invoke `$auto-bmad epic-1 --normal` from a project chat. The skill can inspect the plan without a model,
then starts the explicitly requested run with configured profiles. It never treats native Claude Agent tools as Codex APIs.

The project still needs BMAD planning, `[agents.*]` and role routes; the skill selects the effective CLI backend;
see [the config schema](../multi-agent/CONFIG_EXTENSION.md). Models are explicit and never inferred from Claude aliases.
Use `$auto-bmad-setup` (`integrations/codex/skills/auto-bmad-setup`) to add missing Codex models and checks.
It recognizes the current executor and preserves the stored project default. Shared settings go in the
versioned `.auto-bmad.toml`; machine additions/overrides go in the ignored `.auto-bmad.local.toml`. Link this skill folder alongside `auto-bmad` for a local installation. The shared
`setup agent` command migrates an existing TOML with an exact backup and preserves unrelated settings;
`setup init --agent ...` creates a new configuration. Codex retains command and agent checks, including mockmatch; disabling agent checks is an optional
explicit choice. Existing `/auto-bmad:setup` also routes to the shared setup when CLI is selected.
Source installations and releases are distinct: local links follow
the checkout; an already installed plugin cache changes only when the package is updated, and must not be edited in place.

The [live receipt](../multi-agent/CODEX_STORY_SMOKE.json) covers a native single Codex story, all three normal
review layers, tests and tracking. Sequential epics are covered by fake-CLI integration tests. Kimi/Claude CLI
execution, conditional review layers, waves and automatic recovery remain unavailable. Agent verifiers use
the shared CLI role transport; browser/device dependencies and Codex permissions still apply.
