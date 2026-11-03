---
name: bmad-reviewer-lite
description: Service type for the bmad-build-auto pipeline — the cheapest review layer; only the Intent Alignment Auditor gets it (on `--fast` and `--normal`). Do NOT pick it for ordinary tasks and do not use it instead of /code-review. Model Haiku 5.5, effort high: it fits a closed, descriptive "intent against diff" comparison with no repository walk and no bug hunting. Do not give this type to layers that look for defects or walk the tests. It is started by an instruction in _bmad/custom/bmad-build-auto.user.toml, not by the model's choice.
model: haiku
effort: high
---

Read and follow `../prompts/roles/reviewer-lite.md` and `../integrations/claude/HOST.md`,
resolved relative to this agent definition file (not the project working directory).
The launch prompt may provide their absolute paths. The shared prompt owns the task and
report contract; the Claude adapter owns native invocation, isolation and waiting.
