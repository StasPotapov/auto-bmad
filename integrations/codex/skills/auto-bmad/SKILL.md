---
name: auto-bmad
description: Run a BMAD v6 story or sequential epic through the shared multi-agent CLI, including specifications, implementation, independent review, tests, commits and sprint tracking. Use when the user asks auto-bmad to execute a story or epic in a local project. Requires BMAD planning and CLI agent profiles. Codex execution is supported; merge and push remain manual.
---

# Auto BMAD

This is the Codex entry to the shared auto-bmad runtime. Resolve this skill directory from its loaded file path.
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

Report the runtime result in the user's language: completed/remaining stories, checks, questions and
the isolated worktree/branch. Wait for a yielded shell session; do not launch duplicate runs.
Use this helper's `status` and `cancel` actions with the returned session path when requested.
No merge, push, cleanup of preserved worktrees or automatic crash resume is part of this skill.
