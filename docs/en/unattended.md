# Unattended runs

[Русский](../ru/unattended.md) · [Back to README](../../README.md)

auto-bmad can run an epic with nobody at the keyboard: from a terminal, cron, launchd or CI.
It uses Claude Code's print mode (`claude -p`) with a permissions file.

## 1. The permissions file

```bash
auto-bmad setup headless --repo . --write
```

This writes `.claude/auto-bmad-headless.json` (or `/auto-bmad:setup` does it in stage 5).
Without `--write` it only prints the file and the command. With an existing file, `--write`
exits with code 2; add `--force` to overwrite.

**Allowed** — everything a run needs to live:

- `auto-bmad`, `uv run`;
- git: `status`, `log`, `diff`, `show`, `add`, `commit`, `checkout`, `switch`, `worktree`,
  `merge`, `rev-parse`, `stash`;
- `ls`, `cat`, `grep`, `sed`, `wc`, `mkdir`;
- the first word of the detected test command (for example `npm`, `pytest`, `./gradlew`);
- Android projects: `./gradlew`, `adb`, `adbm`, and the full path of adbm's CLI if found.
- web projects: `mockmatch`, `curl`, the first word of the dev server command
  (for example `npm`), and the full path of mockmatch's CLI if found.

**Denied** — what a person should do:

- `git push`, `git reset --hard`, `git clean -f`, `git branch -D`, `rm -rf`.

A run never pushes. You review the commits and push yourself (or your CI step does it).

Commit the file. An untracked file makes the working tree dirty, and preflight stops on a
dirty tree. If your test command is not detected (you set it in `.auto-bmad.toml`), add it
to `allow` by hand.

## 2. The command

```bash
mkdir -p .auto-bmad/runs
claude -p "/auto-bmad:auto-bmad epic-1" \
  --permission-mode acceptEdits --permission-prompts none \
  --settings .claude/auto-bmad-headless.json \
  --output-format stream-json --verbose > .auto-bmad/runs/epic-1.jsonl
```

- `--permission-mode acceptEdits` — file edits are accepted;
- `--permission-prompts none` — anything that would ask for permission is denied, so the
  run never hangs on a prompt;
- `--settings` — the permissions file above;
- `--output-format stream-json --verbose` — the full run as JSON lines, for reading later.

Write the log under `.auto-bmad/`: that folder is excluded from git. A log file in the
project root would make the tree dirty and stop preflight.

Add a level or other flags inside the quotes: `"/auto-bmad:auto-bmad epic-1 --deep"`.

## Auto mode: the allow rules

A bot or a script can also run Claude Code in auto mode (`"defaultMode": "auto"` in
`settings.json`) instead of the permissions file. Then nobody approves a command. Each call
goes this way: an `allow` or `deny` rule decides at once; reads and file edits in the working
directory pass; everything else goes to a classifier, which at times denies a call. A denied
finishing call loses the commit, the sprint sync, the hook events and the statistics of a
story. So give the run `allow` rules for what it calls, and tell the classifier what a run is.

See what your settings miss for a project:

```bash
auto-bmad setup allow --repo .
```

It merges `allow`, `deny` and `ask` from `~/.claude/settings.json`, `.claude/settings.json`
and `.claude/settings.local.json` and prints:

| Field | What it is |
|---|---|
| `allow` | every rule the run needs for this project |
| `missing` | the rules none of your settings covers. A wider rule counts: `Bash(git:*)` or `Bash(git *)` covers `Bash(git merge:*)`, `Skill(*)` covers `Skill` |
| `dropped_in_auto_mode` | rules auto mode ignores (below): such calls go to the classifier anyway |
| `conflicts` | needed rules that a `deny` or `ask` rule hits: `deny` refuses the call, `ask` waits for a person who is not there |
| `auto_mode_allow` | text for the `autoMode.allow` block (below) |
| `deny` | what to deny |

**Always needed:**

| Rule | What uses it |
|---|---|
| `Read`, `Glob`, `Grep`, `Edit`, `Write` | the engine reads and writes code and specs; the run writes the inputs of `story-finish` |
| `Agent` | the story runner, the implementer, the reviewers, the checks. Auto mode ignores this rule |
| `SendMessage` | the run passes a subagent the result of its own subagents |
| `Skill` | the engine `bmad-build-auto`; the checks call `adbm` and `mockmatch` as skills |
| `TaskCreate`, `TaskUpdate`, `TaskList` | the task list of the run (`TodoWrite` needs no rule: Claude Code allows it by itself) |
| `Bash(auto-bmad:*)` | every script of the run: plan, preflight, sync, questions, `story-finish`, stats |
| `Bash(uv run:*)` | the engine renders its skill with `uv run …/render_skill.py`. Auto mode likely ignores this rule as a package manager's run |
| `Bash(git status:*)`, `Bash(git log:*)`, `Bash(git diff:*)`, `Bash(git show:*)`, `Bash(git rev-parse:*)` | reading the tree, the base of a story, the diff |
| `Bash(git add:*)`, `Bash(git commit:*)` | the engine commits the story, the run commits the tracking and hook files |
| `Bash(git checkout:*)`, `Bash(git switch:*)`, `Bash(git worktree:*)`, `Bash(git merge:*)`, `Bash(git stash:*)` | parallel waves: a branch per story, merging back |
| `Bash(ls:*)`, `Bash(cat:*)`, `Bash(grep:*)`, `Bash(sed:*)`, `Bash(wc:*)`, `Bash(mkdir:*)` | small reads of the engine |

**Depends on the project** (`setup allow` adds them by itself):

| Rule | When |
|---|---|
| the test command | the project has tests. Its first word (`Bash(./gradlew:*)`, `Bash(pytest:*)`); when that word is an interpreter or a package manager, the whole command (`Bash(python3 -m pytest:*)`, `Bash(npm test:*)`) |
| `Bash(./gradlew:*)`, `Bash(adb:*)`, `Bash(adbm:*)` and the full path of adbm's CLI | an Android app: the device check |
| `Bash(mockmatch:*)`, `Bash(curl:*)`, the dev server command (the same rule as for tests), the full path of mockmatch's CLI | a web app: the browser check |
| `mcp__claude_design__list_projects`, `…get_project`, `…list_files`, `…render_preview` | a web app: the design check reads the design from Claude Design when it is set |

**Deny** — what a person does: `Bash(git push:*)`, `Bash(git reset --hard:*)`,
`Bash(git clean -f:*)`, `Bash(git branch -D:*)`, `Bash(rm -rf:*)`.

**What auto mode ignores.** On entering auto mode Claude Code drops `allow` rules that let
any code run: `Bash(*)`, an interpreter by its name (`Bash(python3:*)`), a package manager's
run, and `Agent`. A narrow rule with the whole command stays. That is why `setup allow` gives the
test command whole when it starts with an interpreter. Do not add `Bash(python3:*)` or
`Bash(git -C:*)` "just in case": the first is ignored in auto mode and lets any code run in
the other modes, and the second lets `git -C <dir> push` past the `git push` deny. The run
needs neither.

**Tell the classifier what a run is.** Calls that no rule covers — subagents, `uv run` —
still go to the classifier. The `autoMode` block describes routine work to it in plain words.
Put it into `~/.claude/settings.json` or the project's `.claude/settings.local.json`: Claude
Code does not read it from the shared `.claude/settings.json`. Keep `"$defaults"`, or the
built-in protections are lost:

```json
"autoMode": {
  "allow": [
    "$defaults",
    "auto-bmad runs (the auto-bmad Claude Code plugin with the BMad engine) in this user's own repositories are routine: …"
  ]
}
```

The full text is in `auto_mode_allow` of `setup allow`. `claude auto-mode config` shows the
rules the classifier uses after your settings.

Add all of this yourself: the agent must not edit its own permissions, and auto mode denies
that as self-modification.

The run itself keeps to one `auto-bmad` call per Bash call and passes text through files,
never through heredoc or pipes into `python3 -c`: an allow rule matches a simple command,
and a chain still goes to the classifier. The finishing steps of a story are one command,
`auto-bmad story-finish` (see [CLI](cli.md#story-finish)). Even if a call is denied, the
plugin's `SessionEnd` hook records the session statistics (see [Statistics](stats.md)).

## 3. The example script

The plugin ships `examples/run-epic.sh`:

```bash
run-epic.sh <project dir> <epic-N | N-M> [--fast|--normal|--deep]
```

It changes to the project, writes the log to `.auto-bmad/runs/<YYYYmmdd-HHMMSS>.jsonl` and
runs the command above. Copy it somewhere stable (the plugin's install path changes with
updates):

```bash
cp "$(dirname "$(command -v auto-bmad)")/../examples/run-epic.sh" ~/bin/run-epic.sh
chmod +x ~/bin/run-epic.sh
~/bin/run-epic.sh ~/src/my-app epic-1 --normal
```

`command -v auto-bmad` works inside Claude Code's Bash tool, where the plugin's `bin/` is on
PATH. Outside it, copy the script from the plugin's source repository.

## Time window and usage limits

A run can stop between stories when time or the subscription usage runs out. It never
drops a story it has started: the window only decides whether to take the **next** story
(or wave). The check is `auto-bmad window`; it reads these environment variables:

| Variable | Meaning | Default |
|---|---|---|
| `AUTO_BMAD_DEADLINE` | end of the window, Unix time in seconds | no window |
| `AUTO_BMAD_RESERVE_MINUTES` | minutes a story needs; the next story is taken only if this much time is left (a wave needs 15 more) | 60 |
| `AUTO_BMAD_LIMITS_FILE` | path to a JSON snapshot of subscription usage (see below) | none |
| `AUTO_BMAD_STOP_AT_FIVE_HOUR_PCT` | stop taking stories at this 5-hour window usage, % | no limit |
| `AUTO_BMAD_STOP_AT_SEVEN_DAY_PCT` | stop taking stories at this weekly usage, % | no limit |
| `AUTO_BMAD_LIVE_FILE` | path to a JSON file the runner may change during the run: `deadline`, `reserve_minutes`, `stop_at_five_hour_pct`, `stop_at_seven_day_pct`. Read before every story; a key in it wins over the variable above | none |
| `AUTO_BMAD_STOP_FILE` | path to a stop file: while it exists, the run finishes the current story or wave and takes no more — a clean stop without killing the process | none |

A broken value counts as "no limit". When the window stops a run, the final report is
"run stopped by window" and ends with a machine line:

```
WINDOW_STOP: epic-1 done=2 left=4
```

Other machine lines in the output help a script that watches the stream: `WORK_START`
when a story or wave is taken, `STORY_DONE` and `STORY_BLOCKED` at the end of each story
report. They are printed verbatim in any run language. The full list and a runner that uses
them are in [Integration examples](examples.md#markers-in-the-output).

Example: work for at most 6 hours.

```bash
AUTO_BMAD_DEADLINE=$(( $(date +%s) + 6*3600 )) ~/bin/run-epic.sh ~/src/my-app epic-1
```

The usage snapshot is a file you provide; auto-bmad does not produce it. Its format:

```json
{
  "updated_at": 1760640000,
  "five_hour": {"utilization": 0.42, "resets_at": 1760652000},
  "seven_day": {"utilization": 0.18, "resets_at": 1761100000}
}
```

`utilization` is a fraction (0.42 = 42 %). A snapshot older than 3 hours is ignored, and so
is a window whose `resets_at` is in the past.

## Other environment variables

| Variable | Meaning |
|---|---|
| `AUTO_BMAD_UNATTENDED` | any non-empty value marks the run as unattended: hooks get `"unattended": true` and their questions are dropped. `AUTO_BMAD_DEADLINE` has the same effect |
| `AUTO_BMAD_EVENTS_FILE` | an extra file to append the events journal to |
| `AUTO_BMAD_CONFIG` | path of the personal config instead of `~/.config/auto-bmad/config.toml` |

## cron

```cron
# Every night at 01:00, for at most 5 hours.
0 1 * * * PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin AUTO_BMAD_UNATTENDED=1 AUTO_BMAD_DEADLINE=$(( $(date +\%s) + 5*3600 )) $HOME/bin/run-epic.sh $HOME/src/my-app epic-1 >> $HOME/auto-bmad-cron.log 2>&1
```

cron has a short PATH: make sure `claude`, `git`, `uv` and `python3` are on it. `%` must be
escaped as `\%` in a crontab.

## launchd (macOS)

`~/Library/LaunchAgents/com.example.auto-bmad.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.auto-bmad</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>AUTO_BMAD_DEADLINE=$(( $(date +%s) + 5*3600 )) "$HOME/bin/run-epic.sh" "$HOME/src/my-app" epic-1</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>AUTO_BMAD_UNATTENDED</key><string>1</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>1</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/auto-bmad.out</string>
  <key>StandardErrorPath</key><string>/tmp/auto-bmad.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.example.auto-bmad.plist
```

## CI

A sketch for GitHub Actions. The runner needs Claude Code, its authentication, the plugin,
`uv` and Python 3.11+; the repository must already contain BMad and the plan.

```yaml
name: auto-bmad epic
on:
  workflow_dispatch:
    inputs:
      target: {description: "epic-N or N-M", required: true, default: "epic-1"}
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: astral-sh/setup-uv@v5
      - run: curl -fsSL https://claude.ai/install.sh | bash
      - run: |
          claude plugin marketplace add StasPotapov/sp-tools
          claude plugin install auto-bmad@sp-tools
      - run: |
          git config user.name "auto-bmad"
          git config user.email "auto-bmad@example.com"
          mkdir -p .auto-bmad/runs
          claude -p "/auto-bmad:auto-bmad ${{ inputs.target }}" \
            --permission-mode acceptEdits --permission-prompts none \
            --settings .claude/auto-bmad-headless.json \
            --output-format stream-json --verbose > .auto-bmad/runs/ci.jsonl
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}   # or CLAUDE_CODE_OAUTH_TOKEN
          AUTO_BMAD_UNATTENDED: "1"
      # The run does not push. Push the commits to a branch and open a pull request here.
      - uses: actions/upload-artifact@v4
        with: {name: auto-bmad-log, path: .auto-bmad/}
```

The native installer puts Claude Code on the runner; `npm install -g @anthropic-ai/claude-code`
works too and needs Node.js 22+. For authentication, store one secret: an API key in
`ANTHROPIC_API_KEY`, or a subscription token from `claude setup-token` in
`CLAUDE_CODE_OAUTH_TOKEN`. If both are set, the API key wins. `--permission-prompts none`
needs Claude Code 2.1.259 or later. See [Set up Claude Code](https://code.claude.com/docs/en/setup)
and [Authentication](https://code.claude.com/docs/en/authentication).

The official [Claude Code GitHub Action](https://code.claude.com/docs/en/github-actions)
(`anthropics/claude-code-action@v1`) can also install plugins through its `plugin_marketplaces`
and `plugins` inputs. This page shows the plain CLI because the same command works in cron
and launchd.

## Where logs go

| What | Where |
|---|---|
| Full session (stream-json) | where you redirect it; `run-epic.sh` uses `.auto-bmad/runs/<timestamp>.jsonl` |
| Events journal | `.auto-bmad/events.jsonl` and `$AUTO_BMAD_EVENTS_FILE` |
| Statistics | `.auto-bmad/stats/runs.jsonl` |
| Check state (baseline, fix counters) | `.auto-bmad/verify/` |
| Claude Code transcripts | `~/.claude/projects/<project>/` |
| Results for a person | story and epic reports in the session output; the open-questions file in `_bmad-output/implementation-artifacts/` |
