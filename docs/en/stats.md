# Run statistics

[Русский](../ru/stats.md) · [Back to README](../../README.md)

auto-bmad keeps statistics of every story run in the project: time, tokens by role and
model, subagents, tool calls, review passes and findings, check verdicts. Use them to
compare levels and to see where a run spends its budget.

## Native Codex accounting

`stats show`, `record` and `backfill` collect native journals as well as historical CLI and
Claude data. Native rows include story duration, agents, repairs and technical retries. Run
wall time is shown separately from summed story time, which can overlap in parallel waves.

For local Codex response counters, bind the exact root thread and root turn from the host:

```bash
auto-bmad stats record --repo . --session /absolute/path/to/native/session.json \
  --codex-thread <root-thread-UUID> --codex-turn <root-turn-UUID>
auto-bmad stats show --epic 1 --last 1 --calls --repo .
```

Register at run start and again for each resumed root turn. Binding validates the local
root rollout's repository and turn, and rejects assignment of one root turn to two runs.
Do not run two separately accounted native runs inside the same root turn. Subsequent
`show`/`backfill` refresh bound runs automatically; older runs can be bound with `record`.
Without exposed IDs, retain native timing and unavailable usage rather than guessing.

The collector reads local `$CODEX_HOME/sessions` (default `~/.codex/sessions`), not the private
application database. It follows child ancestry metadata and exact root-turn IDs, summing
`token_usage_record.usage` once per thread/response ID. Cumulative `token_count`, turn/thread
totals and embedded compaction snapshots are never added. Cache and reasoning are subsets
of input and output respectively. A rollout format without per-response records remains
unavailable; missing files and unfinished/invalid measurements are partial or unavailable.

JSON exposes `tokens_with_orchestrator` separately from story-only `tokens`; the table also
shows measured input/output/cache including the main chat. Unknown is displayed as a dash,
never a free call. A bound run may still be partial while the reporting turn is in progress.
Agent paths/thread IDs map measurements to recorded roles; unregistered descendants are
`unattributed` with model `?`, not silently assigned their parent's model. Model/effort labels
are configured values, not provider verification. Only counters/IDs and scheduling shape are
saved in ignored project statistics, never prompts or source text. Historical CLI/Claude
measurements remain separate and are not credited to a native run. The following legacy
collector details describe Claude transcripts.

## Commands

```bash
auto-bmad stats show [--epic N] [--last N] [--calls] [--json] [--repo .]
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
  layers, triager, verifier…), and by role and model together (`by_role_model`): it shows which model
  actually ran in a role after a [`[roles.*]`](config.md#roles) override;
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
average tokens per story, average review passes, findings and subagents, the triage line,
output by role with the models of each role in brackets, top tools. The labels are in English.

The triage line shows how the session that runs a story routed the review findings:
`patch` (fixed), `defer`, `reject` and "to the spec" (`intent_gap`, `bad_spec`), as shares of
the routed findings, then the shares of the `low` and `false` verdicts. The line appears only
when the spec logs hold routed findings. `low` comes mostly from the screening rule (fact B),
`false` from reading the code. If triage gets worse, expect `reject` and `false` to grow and
`patch` to fall. Compare runs of the same level: the level changes the review layers and their
models, and so the findings; `--json` has the line per level under `by_level`. See
[Under the hood](engine.md).

The epic report of a run includes three summary lines from `auto-bmad stats show --last 1`.

## Where the data comes from and where it goes

Source: Claude Code transcripts, not the model's memory —
`~/.claude/projects/<project>/<session>.jsonl` for the orchestrator and
`…/<session>/subagents/agent-*.jsonl` for subagents at any depth
(`$CLAUDE_CONFIG_DIR/projects` if that variable is set). Review findings come from the
spec the story runner named.

Storage: `.auto-bmad/stats/runs.jsonl` in the project (in its main tree, also for a
[run in its own worktree](running.md#run-in-its-own-worktree)), one line per story run plus one per
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
