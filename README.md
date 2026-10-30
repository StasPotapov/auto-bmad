<img src="assets/icon.png" width="96" alt="" align="right">

# auto-bmad

[Русский](README.ru.md)

Automate [BMad](https://github.com/bmad-code-org/BMAD-METHOD) v6 stories and epics through a shared CLI with configured agent roles, or the existing native Claude Code plugin.

## Codex and the shared CLI

The CLI backend routes each role through its configured adapter/model. Codex passed a live story smoke
(spec → implementation → three review layers → tests → commit → tracking). Epics run sequentially in a unique
worktree; merge and push are manual. Native Claude Code retains its existing workflow below. Kimi and Claude
CLI execution are not enabled yet; adding an adapter does not replace the BMAD lifecycle.

Use the Codex skill from `integrations/codex/skills/auto-bmad` or the CLI:

```bash
bin/auto-bmad --executor codex run plan --repo /path/to/project --arg "epic-1"
bin/auto-bmad --executor codex run --repo /path/to/project --arg "epic-1 --normal" --allow-model
```

Use `$auto-bmad-setup` to add the current agent’s settings without editing TOML.
Commit shared defaults in `.auto-bmad.toml`; put personal additions/overrides in the ignored
`.auto-bmad.local.toml`. Skills select the executor from the current chat without changing project defaults.
Existing settings are preserved with a backup; `$auto-bmad` executes a separate run.
The project needs BMAD planning and explicit role profiles.
CLI usage is recorded in the project's `.auto-bmad/stats/runs.jsonl`; `stats show --epic 1 --calls`
shows per-invocation reported tokens, with model/role/epic summaries and explicit unknown usage.
See [CLI/configuration](docs/en/cli.md#cli-backend-codex-and-sequential-epics),
[Codex install](docs/en/install.md#codex-and-local-skill), and the [live validation receipt](docs/multi-agent/CODEX_STORY_SMOKE.json).
The remaining usage examples describe native Claude Code, including its parallel-wave mode.

## What it is

BMad's `bmad-build-auto` engine builds one story at a time, and a long epic run in one
session piles up context until the last stories are slow and expensive. auto-bmad runs
each story in its own subagent, so only a short report comes back. It picks the review
depth by level, can run independent stories of an epic in parallel git worktrees,
checks each story with the project's tests (and on an Android emulator), and lets the
engine fix what the checks find. A run leaves commits, an updated `sprint-status.yaml`,
a report per story and per epic, and one file with the open questions only a human can decide.

## How it works

```
plan ──► story in a subagent ──► review layers ──► checks + fix loop ──► commit, sync, report
 │        (bmad-build-auto)       (by level)        (tests, emulator)          │
 └──────────────────────────── next story or next wave ◄───────────────────────┘
```

1. **Plan** — reads `sprint-status.yaml` and the epics file, builds the queue, runs preflight.
2. **Story in a subagent** — `auto-bmad:bmad-story-runner` runs the engine: spec → code → commit.
3. **Review** — 2, 3 or 4 review layers on different models, depending on the level.
4. **Checks and fix loop** — project tests and other checks; a problem goes back to the
   engine, up to a limit.
5. **Commit and report** — tracking is synced, open questions are written, hooks fire.

The work on a story — spec, code, review, fixes, commit — is done by BMad's engine. auto-bmad
tunes it for runs without a person through a level profile of rules; what each rule changes
is in [Under the hood](docs/en/engine.md).

## Quick start

1. Install the plugin. It lives in the [sp-tools](https://github.com/StasPotapov/sp-tools)
   marketplace with my other plugins. Tell Claude Code "install the auto-bmad plugin from the
   StasPotapov/sp-tools marketplace", or run:

   ```bash
   claude plugin marketplace add StasPotapov/sp-tools
   claude plugin install auto-bmad@sp-tools
   ```

2. Restart Claude Code.
3. In your project folder run `/auto-bmad:setup`. It checks the environment, helps
   install BMad 6.12+ (`npx bmad-method install`, module `bmm`, tool Claude Code),
   walks you to a BMad plan (PRD → architecture → epics → sprint planning) and writes
   `.auto-bmad.toml`. Run it again after each step it sends you to.

Requirements: git, uv, Python 3.11+, BMad 6.12+. Android checks need the
[adbm](https://github.com/StasPotapov/adbm) plugin, web checks the
[mockmatch](https://github.com/StasPotapov/mockmatch) plugin. Details — [Install](docs/en/install.md).

## Running

```
/auto-bmad:auto-bmad epic-1            # a whole epic
/auto-bmad:auto-bmad 1-3               # one story
/auto-bmad:auto-bmad                   # the next story by sprint status
/auto-bmad:auto-bmad epic-1 --deep     # level for this run: --fast | --normal | --deep
/auto-bmad:auto-bmad epic-1 --no-parallel
/auto-bmad:auto-bmad epic-1 --width 2  # at most 2 stories per wave
/auto-bmad:auto-bmad epic-1 --worktree # the run in its own worktree, merge later: auto-bmad land bmad/epic-1
```

At the end you get commits in your current branch (nothing is pushed; with `--worktree` —
in the branch `bmad/<target>`, see [Running](docs/en/running.md#run-in-its-own-worktree)), `sprint-status.yaml`
up to date, a report per story ("what was done", "how to check", "needs attention"), an
epic report, and `_bmad-output/implementation-artifacts/epic-<N>-open-questions.md` with
the open questions. Statistics: `auto-bmad stats show`.

The run talks to you and writes its reports in your language: BMad's `communication_language`,
or the language you write in. Commit messages and machine markers stay in English.

## Configuration

The config is optional: without it a run works on the built-in defaults. `/auto-bmad:setup`
writes the project file `.auto-bmad.toml`; your personal settings go to
`~/.config/auto-bmad/config.toml`, and settings of one project on this machine only — to
`.auto-bmad.local.toml` (out of git). The config sets:

- **run defaults** — the level, parallel waves, the wave width, triage of review findings in a subagent;
- **models** — the model and effort of each role: implementer, reviewers, verifier…;
- **checks after a story** — project tests, an Android emulator, a browser, your own commands,
  and how many fixes they may cause;
- **hooks** — your scripts on run events: a chat message, a task board update.

```toml
[run]
level = "deep"

[roles.implementer]
model = "sonnet"
effort = "high"

[roles.story-runner]
model = "opus[1m]"   # Opus with a 1M context; plain "opus" is the regular context
```

How to set it up and what each key means — [Configuration](docs/en/config.md).

## Unattended

```bash
auto-bmad setup headless --repo . --write    # once: .claude/auto-bmad-headless.json
mkdir -p .auto-bmad/runs
claude -p "/auto-bmad:auto-bmad epic-1" \
  --permission-mode acceptEdits --permission-prompts none \
  --settings .claude/auto-bmad-headless.json \
  --output-format stream-json --verbose > .auto-bmad/runs/epic-1.jsonl
```

For cron, launchd or CI use `examples/run-epic.sh` — see [Unattended runs](docs/en/unattended.md).

## Documentation

| Page | About |
|---|---|
| [Install](docs/en/install.md) | requirements, install, `/auto-bmad:setup` stage by stage, updates |
| [Running](docs/en/running.md) | arguments, what happens per story, reports, resuming, parallel waves |
| [Levels](docs/en/levels.md) | `fast` / `normal` / `deep`, review layers, default models |
| [Under the hood](docs/en/engine.md) | the BMad engine, the level profile and the rules ("facts") that change the engine |
| [Checks](docs/en/checks.md) | project tests, Android emulator checks, fix loop, your own checks |
| [Configuration](docs/en/config.md) | config layers, `[run]`, `[roles.*]`, `[verify_limits]`, `[[verify]]`, `[[hook]]`, examples |
| [Hooks](docs/en/hooks.md) | run events, hook input and output, events journal |
| [Unattended runs](docs/en/unattended.md) | `claude -p`, permissions, time window, cron, launchd, CI |
| [Statistics](docs/en/stats.md) | `auto-bmad stats`, what is measured |
| [CLI](docs/en/cli.md) | every `auto-bmad` subcommand |
| [Integration examples](docs/en/examples.md) | a task board hook, night runs with chat notifications, one tracker task through the story runner |
| [Case study](docs/en/case-study.md) | a real run: an Android app, 4 epics, 28 stories in 10 hours, tokens per epic |

## License

MIT
