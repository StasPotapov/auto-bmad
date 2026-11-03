---
name: auto-bmad-setup
description: Set up auto-bmad in a local project, choose its executor and models, or migrate existing auto-bmad TOML settings while preserving project configuration. Use when the user asks to configure or connect auto-bmad, including native Codex subagents or the native Claude Code workflow. Setup never starts a story or a model.
---

Read `HOST.md` in this skill directory before running tools; it defines portable paths and host capabilities.


# Auto BMAD setup

Resolve this skill directory from its loaded path; it may be a symlink into the source checkout.
Read `../../../../skills/setup/CLI.md` relative to the resolved directory and use its workflow.
Run the shared setup CLI through:

```text
python3 <this-skill-directory>/scripts/setup.py <action> --repo <absolute-project-root> <options>
```

The helper belongs to the whole auto-bmad package; a copied SKILL.md alone is insufficient.
The wrapper above is the Codex adapter. In another host use the shared
`../../../../scripts/setup.py` and `../../../../skills/setup/SKILL.md`; preserve saved
executor/model choices and ask only for missing ones. Do not invoke the Codex
wrapper from another host, because it adds Codex profiles. The remaining
Codex-specific defaults apply only when the current host is Codex.
In Codex do not ask the user to switch from Claude Code or select an executor.
The helper checks native Codex configuration and adds Codex model settings by default, preserving the configured project
default and all native Claude settings. Reuse complete saved Codex profiles; ask only for missing model
choices only for requested customization; built-in Codex models are already available. Explain common
models for all levels and optional fast/normal/deep differences, and preserve client settings in the private local layer by default. Shared model settings require an explicit choice.
After checking an existing project, follow CLI.md's “Explain the existing setup” section: describe the
saved settings, the current agent's addition or reuse, and offer local overrides for personal changes.
Preview, then write the requested addition. An explicit request to change the standalone default may use --select.
Always follow CLI.md's project test strategy step: inspect this project's components, propose their
commands and changed-path rules, discuss shared files and baseline policy, and save the agreed
`project_tests` configuration. Do not assume the project is a web frontend/backend pair.
Never launch a story, invoke a model,
install packages, change hook trust, or merge/push code as a side effect of setup.

Codex uses `execution.backend="native"`. Check actual collaboration-tool availability in the chat;
setup configuration checks cannot prove it. No Codex executable, CLI authentication probe, or model
subprocess is required. Existing CLI-era model/effort choices must survive migration; unsupported
transport-specific choices must be reported rather than silently reinterpreted.
The main chat is the orchestrator. A headless Codex queue is not part of this runtime.

Use the current host identity supplied by this adapter, not executable detection. Native model
settings belong to `[executors.codex]` in `.auto-bmad.local.toml` by default; preserve the other
client's namespace, shared project checks and legacy compatibility. The shared core and role
prompts are client independent. AI Workspace is an installer only, not a runtime dependency.
