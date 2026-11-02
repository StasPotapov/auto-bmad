---
name: auto-bmad
description: Run a BMAD v6 story or epic in dependency-aware parallel waves through the shared multi-agent CLI, including specifications, implementation, independent review, tests, commits and sprint tracking. Use when the user asks auto-bmad to execute a story or epic in a local project. Requires BMAD planning and CLI agent profiles. Completed epics can merge into local main with execution.merge_policy=auto-main; push remains manual.
---

Read `HOST.md` in this skill directory before running tools; it defines portable paths and host capabilities.


# Auto BMAD

This package exposes the shared auto-bmad runtime. In Codex use the wrapper below.
On another host, read `../../../../skills/auto-bmad/SKILL.md` and its backend routing
first: the shared CLI entry is `../../../../scripts/run_queue.py`; it uses the
project's configured executor. Do not use the Codex wrapper there: it explicitly
selects Codex for an invocation. Native Claude execution requires Claude's actual
native agents; unsupported hosts must use a configured supported CLI executor or
report the missing adapter. The Codex-specific paragraphs below apply only in Codex. Resolve this skill directory from its loaded file path.
The folder may be a symlink to the plugin source checkout.

First inspect the request without starting models:

```text
python3 <this-skill-directory>/scripts/run.py plan --repo <absolute-project-root> --arg "<user arguments>"
```

For `backend: cli`, read the shared instructions at `../../../../skills/auto-bmad/CLI.md` relative to
the resolved skill directory. Execute the requested scope through the same helper with `--allow-model`;
do not recreate the BMAD workflow in this chat or launch native subagents yourself.
The user's request to execute the selected story/epic authorizes that invocation using configured profiles.
Keep their model, adapter and permission choices. Planning alone never authorizes execution.

The helper selects Codex for this invocation without changing the default stored in project/local TOML.
If profiles are missing, add Codex settings through the sibling setup skill; do not ask to switch the whole
project away from Claude Code. Never execute the native Claude pipeline as if it were adapted.
For missing setup or a requested migration, use the sibling `auto-bmad-setup` skill; do not ask the
user to edit TOML manually. A request to configure is separate from a request to run a story.
Missing BMAD artifacts, configuration errors and unsupported capabilities remain blockers.

Follow the shared CLI reporting contract: one opening with the level and actual execution plan,
compact story transitions, and one final report with time, commits and a compact token summary by role, model and effort.
Use one row per role/model/effort combination plus the total; put model and effort in parentheses after the readable role name. Show call IDs only on request.
Round counts as REPORTS.md specifies (Russian: `11,5 млн`, `300к`). Use the shared
run.parallel/run.width settings and wave planning instructions in CLI.md. For sequential execution
say: "Stories run one by one, without parallel execution."
For waves explain that stories within a group run together, and show the groups.
Report the runtime result in the user's language: completed/remaining stories, checks, questions and
the isolated worktree/branch. Do not repeat unchanged status or infer internal phases from logs.
Join the yielded shell session and consume its transition events; do not launch duplicate runs
or a periodic `status` loop. `story-selected` / `wave-selected` means preparation was admitted,
not that implementation or a model has started. Report it as preparation, once.
Use this helper's `status` and `cancel` actions with the returned session path only when requested
or when the shell session was lost and recovery needs one state snapshot. A host-required chat
update is not a reason to run `status` again; report only the last confirmed fact, without claiming progress.
With explicit execution.merge_policy="auto-main", a completed epic lands in local main automatically.
Editorial questions are recorded for later and never prompt or gate landing. Report merge failures and checks.
Push, cleanup of preserved worktrees and automatic crash resume remain outside this skill.
