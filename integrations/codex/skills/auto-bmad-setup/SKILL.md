---
name: auto-bmad-setup
description: Set up auto-bmad in a local project, choose its executor and models, or migrate existing auto-bmad TOML settings while preserving project configuration. Use when the user asks to configure or connect auto-bmad, including Codex CLI or the native Claude Code workflow. Setup never starts a story or a model.
---

# Auto BMAD setup

Resolve this skill directory from its loaded path; it may be a symlink into the source checkout.
Read `../../../../skills/setup/CLI.md` relative to the resolved directory and use its workflow.
Run the shared setup CLI through:

```text
python3 <this-skill-directory>/scripts/setup.py <action> --repo <absolute-project-root> <options>
```

The helper belongs to the whole auto-bmad package; a copied SKILL.md alone is insufficient.
This is the Codex host: do not ask the user to switch from Claude Code or select an executor.
The helper checks Codex readiness and adds Codex profiles by default, preserving the configured project
default and all native Claude settings. Reuse complete saved Codex profiles; ask only for missing model
choices only for requested customization; built-in Codex models are already available. Explain common
models for all levels and optional fast/normal/deep differences, and whether settings belong to the shared project or this machine's local layer.
After checking an existing project, follow CLI.md's “Explain the existing setup” section: describe the
saved settings, the current agent's addition or reuse, and offer local overrides for personal changes.
Preview, then write the requested addition. An explicit request to change the standalone default may use --select.
Never launch a story, invoke a model,
install packages, change hook trust, or merge/push code as a side effect of setup.
