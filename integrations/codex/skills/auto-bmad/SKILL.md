---
name: auto-bmad
description: Run a BMAD v6 story or epic through native Codex subagents. The main chat orchestrates stories, tracks progress, resolves failures, and integrates verified results. Includes specifications, implementation, independent review, tests, commits and sprint tracking. Requires BMAD planning and native agent tools. Push remains separate.
---

# Auto BMAD in Codex

Read `HOST.md` before using tools. Resolve this skill's real directory; retain the complete package layout.
Read `../../../../skills/auto-bmad/NATIVE.md` and the native reporting section of
`../../../../skills/auto-bmad/REPORTS.md` before planning or starting work.

**You, the main chat, are the orchestrator.** Run the selected epic or story through native
subagents using the current chat's collaboration tools. Python helpers prepare artifacts,
validate state, run checks, and update tracking. They do not start models or schedule stories.
Do not launch `codex exec`, a model subprocess, or a Python story queue. There is no CLI fallback.

Inspect the requested scope first:

```text
python3 -B <this-skill-directory>/scripts/run.py plan --repo <absolute-project-root> --arg "<user arguments>"
```

Use the returned plan and configured native role models/effort. A request to execute that scope
authorizes its subagents and required local checks; planning alone does not authorize implementation.
The host selects `native` for Codex without rewriting the stored project default. If configuration
or BMAD inputs are missing, use the sibling `auto-bmad-setup` skill. Preserve Claude settings.
Never substitute a model silently or pretend that missing native tools are available.

Keep the main chat active until the authorized work completes or reaches a concrete blocker.
Read agent progress and results, update the table, diagnose failures, and send bounded follow-up tasks.
Reserve slots for implementers and reviewers before starting story controllers. Follow NATIVE.md for
worktree ownership, saved state, repair budgets, resume, cancellation, and final verification.

Report in the user's language. Show the actual plan, then confirmed changes to the progress table:
story, agent, phase, attempt, blocker, next action; include launched/active/finished agent counts.
Do not invent phases or token usage. Finish with completed/remaining stories, commits, checks,
open decisions and preserved worktree/branch paths.

With explicitly configured `execution.merge_policy="auto-main"`, the main chat performs local landing
only after all required verification and tracking succeed. Push, deletion of retained worktrees,
and system boot automation are separate actions. Saved state supports resuming a chat; it does not
promise autonomous work after the app closes.
