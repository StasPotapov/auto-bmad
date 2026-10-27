# Run statistics

[Русский](../ru/stats.md) · [Back to README](../../README.md)

auto-bmad keeps statistics of every story run in the project: time, tokens by role and
model, subagents, tool calls, review passes and findings, check verdicts. Use them to
compare levels and to see where a run spends its budget.

## Commands

```bash
auto-bmad stats show [--epic N] [--last N] [--json] [--repo .]
auto-bmad stats record --session <session id> [--repo .]
auto-bmad stats backfill [--repo .]
```

| Command | What it does |
|---|---|
| `show` | a table per story and a summary for the project. `--epic N` — only epic N; `--last N` — only the last N sessions; `--json` — machine-readable summary and rows |
| `record` | collects one Claude Code session and writes it to the project. The run calls it itself after every story (in parallel mode, once per wave) through `auto-bmad story-finish --session ${CLAUDE_SESSION_ID}`, and the plugin's `SessionEnd` hook calls it once more when the session ends |
| `backfill` | collects past sessions of this project that are not recorded yet — for runs made before statistics existed, or if `record` failed. Recorded sessions keep their rows |

Exit codes: 0 — done, 1 — call error, 2 — nothing to record or show.

## What is measured

Per story:

- id, epic, level, status (`done` / `blocked`), commit, number of changed files;
- start, end, minutes. The end is the last report of the story's runs and checks: an agent
  that wakes up after its report (a background command finished) does not stretch the story.
  Minutes are the busy time of the story's runs and checks: the union of their spans from
  start to report. Overlaps count once, and a pause between a blocked run and its rerun does
  not count, so minutes can be less than end minus start;
- tokens: total, by model, and by role (orchestrator, story runner, implementer, review
  layers, verifier…);
- subagents by type; tool calls by tool name;
- review passes used, whether a follow-up review stayed open, deferred findings;
- review passes and findings by verdict, route and review layer, from the spec's
  `## Review Triage Log` (layers by BMad's names: blind, edge, intent, verification).
  A spec of a parallel story is read from the main tree when its worktree is gone;
- fix runs after checks and the verdicts of each check. A story rerun before its first check
  is not a fix run.

Per session, a separate row for the orchestrator: time, tool calls and tokens.

Example of `show`:

```bash
auto-bmad stats show --epic 1
```

The table has columns story, level, status, minutes, output≈, input, cache, agents,
passes, findings, followed by summary lines: stories (done / blocked) and total time,
average tokens per story, average review passes, findings and subagents, output by role,
top tools. The labels are in English.

The epic report of a run includes three summary lines from `auto-bmad stats show --last 1`.

## Where the data comes from and where it goes

Source: Claude Code transcripts, not the model's memory —
`~/.claude/projects/<project>/<session>.jsonl` for the orchestrator and
`…/<session>/subagents/agent-*.jsonl` for subagents at any depth
(`$CLAUDE_CONFIG_DIR/projects` if that variable is set). Review findings come from the
spec the story runner named.

Storage: `.auto-bmad/stats/runs.jsonl` in the project, one line per story run plus one per
session for the orchestrator. The folder is excluded from git locally through
`.git/info/exclude`. Recording the same session again replaces its lines.

**Safety net.** The plugin has a `SessionEnd` hook: when a session that ran
`bmad-story-runner` ends, the hook records it with `stats record`. Claude Code runs the hook,
not the model, so permissions do not apply and a denied call in the run loses nothing. The
hook starts the record in the background and exits at once: Claude Code gives a plugin's
`SessionEnd` hook only 1.5 seconds. Other sessions are skipped.

Only counters are stored: ids, level, status, time, counts, tokens, tool and agent type
names. No prompt text, no code, no paths, no finding texts.

## Caveat: output tokens are estimated

- **Input and cache tokens are exact** — taken from the transcript.
- **Output tokens are an estimate** (marked `≈`): computed from the visible answer text and
  tool inputs at about 3.5 characters per token. The transcript records `output_tokens`
  at the start of an answer, and that number is several times too low.
- The model's reasoning is not included in the estimate.
- Prices are not computed.
