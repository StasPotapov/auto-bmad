---
name: setup
description: Sets up auto-bmad in a project, selects Codex CLI or the native Claude Code executor, configures models and project tests, and safely migrates existing TOML settings. Checks BMAD/planning prerequisites and preserves the legacy Claude setup, checks and unattended workflow.
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
auto-bmad --executor claude setup check --repo .
```

Before choosing the next stage, read [CLI.md — Explain the existing setup](CLI.md#explain-the-existing-setup)
and explain the observed shared/local settings. Offer local overrides for personal changes in an
already configured project, including when `ready: true`. This paragraph applies to native Claude too;
it does not route the person into the Codex setup steps.

`next` is the first unfinished stage. Go to its section below. `ready: true` with
`project.config` present — the project is set up: go to section 5 (optional extras)
or section 6.

This frontend is native Claude Code: use `auto-bmad --executor claude` for the commands below and
add native settings with `setup agent --agent claude --add` when needed, without switching the stored default.
Do not ask which executor to use when the current host is known. For an explicit CLI configuration request,
read [CLI.md](CLI.md) and follow its shared setup flow instead. Never run the Claude-only model,
permission, headless or verifier steps below when configuring CLI execution explicitly.
Kimi/Claude CLI adapters remain unavailable.

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

Ask the decisions in **one** `AskUserQuestion` call (up to four questions). Questions
past the fourth go into a second call; the design question (6) always goes after the
web answer, because it depends on it. Put the pros and cons in option descriptions, short.

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
5. **Web checks** — ask only if `project.web` is set: check each UI story in a headless
   browser with mockmatch (Recommended), or tests only. Say why in the option: the checker
   reads the page as text and compares it with the design in numbers, so it is deterministic
   and costs far fewer tokens than screenshots. Show `project.web.serve` and `project.web.url`
   and ask the person to correct them if they are wrong.
6. **Design** — ask only with web checks on: where the design is. Options: a Claude Design
   project (Recommended when the person draws in Claude Design: the check pulls a fresh copy
   for each story), a claude.ai artifact of type "Design" (list them with `Artifact`
   `action: "list"`, `type: "Design"`), a file in the repository (an HTML mockup, a PNG, a copy saved with
   `mockmatch pull`), or no design (feature checks only). For Claude Design, if
   `extras.claude_design.state` is `connected`, call `mcp__claude_design__list_projects` and offer
   the projects as options, then `list_files` and offer the `.dc.html` files; otherwise ask for
   the `claude.ai/design/p/…` link. The answer goes to `--design-project` (the id or the link) and
   `--design-file`; a file in the repository goes to `--design`. Both can be set: the file is then
   the fallback when Claude Design is not logged in.
   A Design artifact goes to `--design-artifact` **and** needs a saved copy in `--design`: an
   unattended run (`claude -p`) has no `Artifact` tool. Make the copy now: call the `mockmatch`
   skill, import the screen the stories build (its "A Design artifact" steps), commit `design/`,
   and pass `--design design/<Screen>.dc.html`.

By default the level picks the models; `[roles.*]` overrides any role (see "Models of the
roles" in step 5 and `docs/en/config.md`). Show this table (the defaults) only if the person
asks about models or cost:

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
    [--no-android] [--no-web] [--design-project <id|link>] [--design-file <file>] \
    [--design-artifact <link>] \
    [--design <path>] --write
```

- `test_command` is empty — ask the person for the command that runs all tests and
  repeat with `--test-command "<cmd>"`, or leave project tests off;
- code 2, `exists: true` — the file is already there: show the difference between
  `content` and the file and ask before `--force`.

Tell the person in one line that settings for this machine only go to
`.auto-bmad.local.toml` next to it (it wins over `.auto-bmad.toml`). `project.local` of
`setup check` has `fix` — the file is not closed from git, or is committed: offer
`auto-bmad setup local --repo . --write` (it adds the file to `.gitignore`); for a committed
file also `git rm --cached .auto-bmad.local.toml`, which the person runs.

Android with checks on and `extras.adbm` false — adbm is not installed. Give the two
commands to run (the person runs them, then restarts Claude Code):
`claude plugin marketplace add StasPotapov/sp-tools` and `claude plugin install adbm@sp-tools`.
Without adbm the device check is skipped with a note in each report.

Web with checks on and `extras.mockmatch` false — mockmatch is not installed. Offer it as a
recommendation, not a requirement: give the commands to run (the person runs them, then
restarts Claude Code) — `claude plugin marketplace add StasPotapov/sp-tools` and
`claude plugin install mockmatch@sp-tools`, then `mockmatch doctor --install` through the agent
(a private venv with Playwright and Chromium). If the person declines, keep the block: without
mockmatch the browser check is skipped with a note in each report. `serve` or `url` corrected —
edit them in `.auto-bmad.toml` after it is written.

Claude Design chosen and `extras.claude_design.state` is not `connected` — the design check cannot
pull the design: `message` says what to do. `missing` — give the `claude mcp add …` command from
it; `auth` — the person logs in with `/mcp` → `claude_design` → Authenticate. Then call `setup check`
again and show the new state. Before each run `auto-bmad preflight --level <level>` asks the same:
without the login it warns when `design` names a saved copy, and blocks the run when there is none.

Offer to commit `.auto-bmad.toml` (it belongs in the repository).

## 5. Optional extras

One `AskUserQuestion` with `multiSelect: true`, all options optional:

- **Unattended runs** — run epics from a terminal, cron, launchd or CI:
  `auto-bmad setup headless --repo . --write` writes
  `.claude/auto-bmad-headless.json` (permissions; `git push` and destructive git are
  denied). Show the `command` from the output and the example script
  `${CLAUDE_PLUGIN_ROOT}/examples/run-epic.sh`. Offer to commit the file.
  If the person runs auto-bmad from a bot or a script in auto mode (`"defaultMode": "auto"`)
  instead, call `auto-bmad setup allow --repo .` and show: `missing` — the rules to add to
  `permissions.allow`; `conflicts` — `deny` or `ask` rules that block the run;
  `auto_mode_allow` — the `autoMode.allow` block for the classifier, since auto mode ignores
  `dropped_in_auto_mode`. The person adds all of it to `~/.claude/settings.json` (or the
  project's `.claude/settings.local.json`) themselves — do not edit those files: auto mode
  denies an agent's edit of its own permissions. The table of what each rule is for —
  `docs/en/unattended.md`, "Auto mode".
- **Hooks** — a script on run events (`story-done`, `story-blocked`, `run-end`, …): a
  Telegram message, a task-board update, anything. Copy
  `${CLAUDE_PLUGIN_ROOT}/examples/hook-template.py` where the person wants it and add a
  `[[hook]]` block — personal hooks in `~/.config/auto-bmad/config.toml`, project
  hooks in `.auto-bmad.toml`. Write the hook's logic only on request.
- **Models of the roles** — another model or effort for a role (implementer, reviewers,
  verifier…) than its agent type default. Show the defaults with `auto-bmad roles --repo .`,
  ask which role and what value, then `auto-bmad setup role --role <role> [--model M]
  [--effort E] [--layer project|user|local] --repo . --write` (no `--model` and no `--effort` removes
  the override). Use project for shared defaults, local for this machine's ignored overrides, and user
  for personal defaults across projects. Only the Anthropic aliases `sonnet`, `opus`, `haiku`, `fable` — another
  provider is not supported yet. For Opus with a 1M context write `opus[1m]` (story-runner
  and implementer only — their agent types carry it); plain `opus` drops the 1M context:
  say so. Details — `docs/en/config.md`, `[roles.*]`.
- **Nothing more** — go on.

## 6. Final check and how to work

```bash
auto-bmad preflight --repo . --level <default level>
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
