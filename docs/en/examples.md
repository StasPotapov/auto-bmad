# Integration examples

[Русский](../ru/examples.md) · [Back to README](../../README.md)

The author runs auto-bmad with a task board, night runs with chat notifications and a skill
that takes single issues from a tracker. None of this is in the plugin. Each setup is built
from the parts the plugin gives you: [hooks](hooks.md), the [config](config.md), the
[markers in the output](#markers-in-the-output) and the `auto-bmad:bmad-story-runner` agent.
Use them as patterns for your own setup.

## Task board sync — a hook

A hook mirrors the run to a self-hosted Gitea board. An epic becomes a milestone, a story
becomes an issue, and the card moves through the columns as the run goes.

```toml
# ~/.config/auto-bmad/config.toml — the personal layer, so every project gets it
[[hook]]
name = "board"
events = ["run-start", "story-start", "story-done", "story-blocked"]
command = "python3 ~/hooks/board_sync.py"
```

| Event | What the hook does |
|---|---|
| `run-start` | checks that the project is connected to a board. If not and a person is present, it returns `ask` with the options "connect", "connect all" and "decline" |
| `story-start` | creates the issue if needed and moves it to "In progress" |
| `story-done` | reads `## Auto Run Result` from the spec and the story section from `questions_file`. Then it posts a report to the issue, moves it to "Review" and adds a "questions" label if the story has open questions |
| `story-blocked` | adds a "blocked" label and posts what stopped the story |

The hook never stops the run. On any error it returns `"ok": false` with a `message` and exits
with code 0. auto-bmad then shows the message, and the run goes on.

## Night runs with notifications — an external runner

A scheduler on a home server runs epics at night and reports to a chat bot. The bot can also
start a run now or schedule one for the night.

1. Before a session the runner updates the plugin: `git pull` in the plugin clone, then
   `claude plugin update auto-bmad@auto-bmad`.
2. The runner starts `claude -p "/auto-bmad:auto-bmad epic-N --normal"` with a time window
   and usage limits from [Unattended runs](unattended.md#time-window-and-usage-limits):
   `AUTO_BMAD_DEADLINE`, `AUTO_BMAD_RESERVE_MINUTES`, `AUTO_BMAD_LIMITS_FILE`,
   `AUTO_BMAD_STOP_AT_FIVE_HOUR_PCT`, `AUTO_BMAD_STOP_AT_SEVEN_DAY_PCT`.
3. The runner reads the `stream-json` output line by line. It sends a chat message on each
   marker (table below).
4. The runner takes the subscription usage from the `rate_limit_event` lines of the stream
   and writes it to `AUTO_BMAD_LIMITS_FILE`. auto-bmad reads that file between stories and
   stops taking new stories near the limit.
5. The runner starts the next epic while time is left in the window.

### Markers in the output

auto-bmad prints these lines verbatim, each on its own line, in every run language.

| Marker | When | What the runner can do |
|---|---|---|
| `WORK_START: story <id>` or `WORK_START: wave <n> (<ids>)` | a story or a wave is taken | if the window is already over, stop the run: the rule "take nothing after the window" is broken |
| `STORY_DONE: <id> commit=<sha> files=<n>` | last line of a story report | send "story done" with the commit |
| `STORY_BLOCKED: <id>` | last line of a "story blocked" report | send an alert |
| `WINDOW_STOP: epic-<N> done=<X> left=<Y>` | last line of a run stopped by the window | treat the run as a normal stop, not a crash |

The events journal (`AUTO_BMAD_EVENTS_FILE`, see [Hooks](hooks.md#events-journal)) gives the
same facts as JSON lines, if you prefer a file to the stream.

## One task from a tracker — your own skill and the story runner

A personal skill takes an issue by its number and runs it through the same engine, outside
any epic. It uses the plugin's CLI and the `auto-bmad:bmad-story-runner` agent in task mode.

1. Check the project and write the level profile:

   ```bash
   auto-bmad preflight --repo .
   auto-bmad profile --level normal --repo .
   ```

2. Start an `Agent` of type `auto-bmad:bmad-story-runner` with this prompt:

   ```
   Run one task through the BMad engine and return a report by your type's contract.

   Task: #12 — Export the dictionary to a file
   Spec slug: issue-12
   Run level: normal
   Review pass limit: 2
   Project root: /path/to/project
   Language: English

   <the issue text and comments as is>
   ```

   The engine names the spec `spec-issue-12-….md`. On a second call, pass `Spec: <path>`
   and the runner continues the same spec.
3. After `STATUS: done`, run the checks as in Step 3.5 of the skill:
   `auto-bmad verify plan`, then the checks, then the fix loop. In the verifier prompt write
   `Story: issue-12 — <title>`, so that statistics put the check under the same task.
4. Post the report to the issue and move the card.

`auto-bmad stats record` counts such a run as a task, with the spec slug as its id.
