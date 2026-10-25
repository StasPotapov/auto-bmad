---
name: setup
description: Sets up a project for auto-bmad step by step — checks the environment, helps install or update BMad, explains the BMad planning that must exist before a run, writes .auto-bmad.toml (default level, parallel waves, project tests, Android checks via adbm), and optionally prepares hooks and unattended runs (claude -p, cron, CI). Re-entrant — call it again after each step it sends you away for.
when_to_use: "First use of auto-bmad in a project, or the user says \"set up auto-bmad\", \"configure auto-bmad\", \"connect auto-bmad to the project\", or the same in another language. Also when /auto-bmad:auto-bmad stopped on preflight and suggested setup."
allowed-tools: Read Bash AskUserQuestion Skill
---

# auto-bmad setup

You walk a person through connecting auto-bmad to the project in the current directory.
The person may know neither BMad nor auto-bmad. Talk in their language (the language
they write in), keep every explanation to two or three sentences, and do the work
yourself — they only answer questions at the key decisions.

The CLI is `auto-bmad` (the plugin's `bin/` is on PATH). If the command is missing,
call it by path: `${CLAUDE_PLUGIN_ROOT}/bin/auto-bmad`.

## 0. Introduce and check

Say in two sentences what auto-bmad is: it runs BMad stories and whole epics without a
human — each story in its own subagent, reviewed, checked by the project's tests (and on
an emulator for Android), committed, with a report and open questions at the end.

Then always start from the facts, never from memory of an earlier call:

```bash
auto-bmad setup check --repo .
```

`next` is the first unfinished stage. Go to its section below. `ready: true` with
`project.config` present — the project is set up: go to section 5 (optional extras)
or section 6.

## 1. Environment (`env`)

Missing `git`, `uv`, Python 3.11+, or the folder is not a git repository — name what
is missing with the install command for the user's OS (`brew install uv`,
`git init`, …). Do not install system packages yourself. Ask them to fix it and call
`/auto-bmad:setup` again.

## 2. BMad (`bmad`)

auto-bmad drives BMad's `bmad-build-auto` engine, so BMad 6.12+ with the `bmm` module
must be installed in the project.

**Not installed** — ask with `AskUserQuestion`:

- **"I'll run the installer myself" (Recommended)** — the installer asks a few questions
  (name, language, folders) that are better answered by the person. Give them exactly:
  1. Open a terminal in this folder: `cd <absolute path>`.
  2. Run `npx bmad-method install`, choose the **BMad Method (bmm)** module and the
     **Claude Code** tool.
  3. Restart Claude Code in this folder and run `/auto-bmad:setup` again.
- **"Install it for me with defaults"** — run
  `npx bmad-method install --yes --modules bmm --tools claude-code` (needs `npx`;
  `env.npx: false` → offer Node.js first). Then tell them to restart Claude Code and run
  `/auto-bmad:setup` again: new BMad skills appear only after a restart.

**Too old** (`version_ok: false`) or no engine (`engine: false`) — same question, with
the update command `npx bmad-method install --yes --action update --modules bmm`.
Warn in one line that the update rewrites BMad's own files under `_bmad/` and
`.claude/skills/`; the person's planning files in `_bmad-output/` stay.

## 3. Plan (`plan`)

auto-bmad implements stories; it does not invent the product. It needs an epics file
and `sprint-status.yaml`, made with the person in BMad's planning skills. Explain the
path in one line each:

| Step | BMad skill | Result |
|---|---|---|
| Requirements | `bmad-prd` (optionally `bmad-product-brief` first) | PRD |
| Architecture | `bmad-create-architecture` | architecture document |
| Epics and stories | `bmad-create-epics-and-stories` | epics file |
| Sprint planning | `bmad-sprint-planning` | `sprint-status.yaml` |

Not sure where they are — `bmad-help` tells the next step. Ask with `AskUserQuestion`:
start planning now (invoke the next skill with `Skill`) or later. Planning is a
conversation with the person; do not fill it in on your own. When planning is done,
`/auto-bmad:setup` again.

## 4. Project settings (`project`)

Ask the decisions in **one** `AskUserQuestion` call (up to four questions). Put the
pros and cons in option descriptions, short.

1. **Default level** — the review depth for every run (a run can override it with
   `--fast` / `--deep`):
   - `normal` (Recommended) — 3 review layers, up to 2 review passes, project tests and
     device checks with up to 2 fixes. Everyday work; about 20–25 minutes per story on
     the author's projects.
   - `fast` — 2 review layers, 1 pass, no checks after a story. Cheapest and
     quickest; for mechanical work (configs, renames, small fixes).
   - `deep` — 4 review layers on stronger settings, up to 3 passes, up to 3 fixes.
     Slowest and most expensive; for money, migrations, public contracts.
2. **Parallel stories** — stories of one epic in git worktrees, in waves:
   - `conservative` (Recommended) — only stories that do not touch the same files,
     3 at a time. Faster epics; uses your rate limit faster.
   - `aggressive` — more stories per wave; more merge conflicts to resolve.
   - `off` — one story at a time. Simplest, slowest.
3. **Android app module** — ask only if `project.android.candidates` has more than
   one module; options are the modules, the detected one first.
4. **Android checks** — ask only if the project is Android: check each UI story on an
   emulator with adbm (Recommended), or tests only.

Models are fixed per level in this version (the level picks them). Show this table
only if the person asks about models or cost:

| Role | fast | normal | deep |
|---|---|---|---|
| Story runner, implementer | Opus | Opus | Opus |
| Edge Case Hunter | Sonnet, medium | Sonnet, medium | Sonnet, high |
| Blind Hunter | off | Sonnet, medium | Sonnet, high |
| Intent Alignment Auditor | Haiku, high | Haiku, high | Sonnet, high |
| Verification Gap Reviewer | off | off | Sonnet, high |
| Checks after a story (verifier) | — | Sonnet, medium | Sonnet, medium |

Then write the file and show it:

```bash
auto-bmad setup init --repo . --level <level> --parallel <mode> [--android-module <m>] \
    [--no-android] --write
```

- `test_command` is empty — ask the person for the command that runs all tests and
  repeat with `--test-command "<cmd>"`, or leave project tests off;
- code 2, `exists: true` — the file is already there: show the difference between
  `content` and the file and ask before `--force`.

Android with checks on and `extras.adbm` false — adbm is not installed. Give the two
commands to run (the person runs them, then restarts Claude Code):
`claude plugin marketplace add StasPotapov/adbm` and `claude plugin install adbm@adbm`.
Without adbm the device check is skipped with a note in each report.

Offer to commit `.auto-bmad.toml` (it belongs in the repository).

## 5. Optional extras

One `AskUserQuestion` with `multiSelect: true`, all options optional:

- **Unattended runs** — run epics from a terminal, cron, launchd or CI:
  `auto-bmad setup headless --repo . --write` writes
  `.claude/auto-bmad-headless.json` (permissions; `git push` and destructive git are
  denied). Show the `command` from the output and the example script
  `${CLAUDE_PLUGIN_ROOT}/examples/run-epic.sh`. Offer to commit the file.
- **Hooks** — a script on run events (`story-done`, `story-blocked`, `run-end`, …): a
  Telegram message, a task-board update, anything. Copy
  `${CLAUDE_PLUGIN_ROOT}/examples/hook-template.py` where the person wants it and add a
  `[[hook]]` block — personal hooks in `~/.config/auto-bmad/config.toml`, project
  hooks in `.auto-bmad.toml`. Write the hook's logic only on request.
- **Nothing more** — go on.

## 6. Final check and how to work

```bash
auto-bmad preflight --repo .
auto-bmad verify baseline --repo .
```

`blocking` not empty — say what and how to fix it. Baseline `problem` — the project's
tests already fail; say that auto-bmad will not try to fix them.

Finish with a short how-to, in the person's language:

- `/auto-bmad:auto-bmad epic-1` — run a whole epic; `/auto-bmad:auto-bmad 1-3` — one
  story; add `--fast` or `--deep` to change the level for this run.
- During a run: a progress line per story; at the end a report per story and the epic's
  open questions file — decisions only a human can make.
- `auto-bmad stats show` — time, tokens and review findings per story.
- Settings later: edit `.auto-bmad.toml`, or call `/auto-bmad:setup` again.
