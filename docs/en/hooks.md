# Hooks

[Русский](../ru/hooks.md) · [Back to README](../../README.md)

A hook is a command that auto-bmad calls on run events: send a notification, update a
task board, write a log — anything of your own. JSON goes in on stdin, JSON comes out on
stdout. **A hook never stops a run**: an error becomes one line in the report.

## Register a hook

In your personal config (`~/.config/auto-bmad/config.toml`) or in the project's
`.auto-bmad.toml`:

```toml
[[hook]]
name = "notify"
events = ["story-done", "story-blocked", "run-end"]
command = "python3 ~/my-hooks/notify.py"
timeout = 60
```

| Field | Meaning |
|---|---|
| `name` | identifier; layers merge by it |
| `events` | which events call this hook |
| `command` | run through `sh -c` from the project root; `@plugin` expands to the plugin directory |
| `timeout` | seconds, default 120; a hook that does not answer in time is reported as an error |
| `enabled` | `false` turns it off (for example, a personal hook in one project) |

## Events

| Event | When | Filled fields |
|---|---|---|
| `run-start` | once per run, before preflight | `epic`, `level` |
| `story-start` | a story is taken: after its preflight (sequential), or at the start of its wave (parallel) | `story`, `title`, `epic`, `level` |
| `verify-done` | after the checks step of a story, once | `story`, `status` (`pass`, `problem`, `skipped`), `data`: `{"fixes": N, "checks": {"<name>": "<verdict>"}}` |
| `story-done` | after the sprint-tracking commit of a finished story | `story`, `status` = `done`, `spec`, `commit`, `questions_file` |
| `story-blocked` | a story stopped; after its notes are committed to the open-questions file | `story`, `status` = `blocked`, `spec`, `commit`, `questions_file` |
| `wave-merged` | once per parallel wave, after its tracking commit | `epic`, `data`: `{"wave": N, "stories": ["1-2", "1-3"]}` |
| `run-end` | exactly once per run, on any outcome, before the final report | `epic`, `level`, `status` (`done`, `blocked`, `window`), `data`: `{"done": N, "left": M}` |
| `answer` | a person answered a hook's question; sent only to that hook | `data`: `{"answer": "<option id>"}` |

`story-done` comes after the commit on purpose: the hook can read the spec and the story's
section of the open-questions file from disk.

## Input (stdin)

```json
{
  "event": "story-done",
  "repo": "/path/to/project",
  "unattended": false,
  "story": "1-3",
  "title": "CSV import",
  "epic": "1",
  "level": "normal",
  "spec": "_bmad-output/implementation-artifacts/spec-1-3-csv-import.md",
  "commit": "a1b2c3d",
  "status": "done",
  "questions_file": "_bmad-output/implementation-artifacts/epic-1-open-questions.md",
  "data": {}
}
```

Fields not relevant to the event are `null`. `unattended` is `true` when the environment has
`AUTO_BMAD_UNATTENDED` or `AUTO_BMAD_DEADLINE` set (see [Unattended runs](unattended.md)).

## Output (stdout)

```json
{
  "ok": true,
  "message": "story 1-3 done: a1b2c3d",
  "link": "https://tracker.example.com/task/42",
  "files": ["docs/changelog/1-3.md"]
}
```

| Field | Meaning |
|---|---|
| `ok` | `true` / `false`. Missing — taken from the exit code (0 is `true`) |
| `message` | one line shown to the person as is |
| `link` | a link added to the story report as `<name>: <link>` |
| `files` | files the hook created in the working tree. auto-bmad commits exactly these files, with `message` as the commit message |
| `ask` | a question for a person (see below) |

Empty stdout means `{}`. Output that is not a JSON object is an error. A hook with
`ok: false` and no `message` is reported as an error with its stderr.

### `ask` — a question for a person

```json
{
  "ok": true,
  "ask": {
    "question": "Create a board column for epic 1?",
    "options": [
      {"id": "yes", "label": "Create", "description": "Adds a column named after the epic"},
      {"id": "no", "label": "Skip", "description": "Nothing changes"}
    ]
  }
}
```

The run asks only on `run-start`, before the first story. The person's choice goes back to
the same hook as the `answer` event with `data.answer` = the option `id`. You can also send
it by hand:

```bash
auto-bmad ext answer --hook notify --option yes --repo .
```

If the person answers something else ("later"), nothing is sent and the hook can ask next
time. In unattended runs (`AUTO_BMAD_UNATTENDED` or `AUTO_BMAD_DEADLINE` set) questions are
dropped: nobody would answer them.

## Events journal

Every event is appended to `.auto-bmad/events.jsonl` in the project (excluded from git
locally) and, if set, to the file in `AUTO_BMAD_EVENTS_FILE`. Only ids, statuses and time
are written — no texts:

```json
{"ts": "2026-10-16T21:04:11+02:00", "event": "story-done", "story": "1-3", "epic": "1", "level": "normal", "status": "done", "commit": "a1b2c3d", "hooks": {"notify": 0}}
```

`hooks` maps each called hook to its exit code (`null` if it did not finish).

## Fire an event by hand

To test a hook without a run:

```bash
auto-bmad ext fire story-done --story 1-3 --status done --commit a1b2c3d --repo .
```

`fire` always exits with 0; the outcome of each hook is in `results`. Note that this also
writes a line to the events journal.

## Template

The plugin ships `examples/hook-template.py`. Copy it, edit `handle`, register it:

```python
#!/usr/bin/env python3
import json
import sys


def handle(event):
    kind = event.get("event")
    if kind == "story-done":
        return {"ok": True, "message": f"story {event.get('story')} done: {event.get('commit')}"}
    if kind == "story-blocked":
        return {"ok": True, "message": f"story {event.get('story')} blocked"}
    if kind == "run-end":
        return {"ok": True, "message": f"run finished: {event.get('status')}"}
    return {"ok": True}


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
    except Exception as e:  # a hook must answer JSON even when it fails
        result = {"ok": False, "message": f"hook failed: {e}"}
    print(json.dumps(result, ensure_ascii=False))
```

## Example: desktop notification on macOS

`~/.config/auto-bmad/hooks/notify.py`:

```python
#!/usr/bin/env python3
"""Shows a macOS notification when a story stops or a run ends."""
import json
import subprocess
import sys

event = json.load(sys.stdin)
kind = event.get("event")
if kind == "story-blocked":
    text = f"Story {event.get('story')} is blocked"
elif kind == "run-end":
    data = event.get("data") or {}
    text = f"Run {event.get('status')}: {data.get('done')} done, {data.get('left')} left"
else:
    print(json.dumps({"ok": True}))
    sys.exit(0)

subprocess.run(["osascript", "-e",
                f'display notification {json.dumps(text)} with title "auto-bmad"'],
               check=False)
print(json.dumps({"ok": True}))
```

Register it in `~/.config/auto-bmad/config.toml`:

```toml
[[hook]]
name = "desktop-notify"
events = ["story-blocked", "run-end"]
command = "python3 ~/.config/auto-bmad/hooks/notify.py"
timeout = 30
```

Test it:

```bash
echo '{"event": "story-blocked", "story": "1-3"}' | python3 ~/.config/auto-bmad/hooks/notify.py
```
