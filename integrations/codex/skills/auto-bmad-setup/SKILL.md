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
Choose the executor with the user, keep existing settings, preview the change, then write the selected
configuration within their request. Ask only for missing decisions. Never launch a story, invoke a model,
install packages, change hook trust, or merge/push code as a side effect of setup.
